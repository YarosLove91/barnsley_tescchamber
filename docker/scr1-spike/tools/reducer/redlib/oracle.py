import hashlib
import json
import os
import time

from . import rtl as rtlmod
from . import spike as spikemod

STATUSES = ("SameBug", "OtherBug", "NoBug", "InvalidProgram", "TimeoutNoDump", "Nondeterminism")
CACHE_VERSION = "v3"
EPILOGUE_MARKER = "R"


class Signature80:
    """mcycleh-расхождение SCR1 issue #80: Spike mcycleh=0/a0 bit0=0,
    RTL mcycleh!=0/a0 bit0=1, триггер исполнен, chk_a/chk_b идентичны."""

    kind = "mcycleh_divergence"

    def __init__(self, trigger_range):
        self.trigger_range = trigger_range


class OracleResult:
    def __init__(self, status, spike=None, rtl=None, cached=False, runs=None, detail=None):
        self.status = status
        self.spike = spike
        self.rtl = rtl
        self.cached = cached
        self.runs = runs or 1
        self.detail = detail or {}

    def to_dict(self):
        return {
            "status": self.status,
            "cached": self.cached,
            "runs": self.runs,
            "detail": self.detail,
            "spike": self.spike.to_dict() if self.spike is not None else None,
            "rtl": self.rtl.to_dict() if self.rtl is not None else None,
        }


class Oracle:
    def __init__(self, env, sig, cache_path=None, use_cache=True,
                 spike_timeout=300.0, rtl_timeout=300.0, save_spike_logs=True):
        self.env = env
        self.sig = sig
        self.cache_path = cache_path or os.path.join(env.out, "oracle_cache.json")
        self.use_cache = use_cache
        self.spike_timeout = spike_timeout
        self.rtl_timeout = rtl_timeout
        self.save_spike_logs = save_spike_logs
        self.cache = {}
        if os.path.exists(self.cache_path):
            try:
                with open(self.cache_path) as f:
                    self.cache = json.load(f)
            except (OSError, ValueError):
                self.cache = {}

    def _save_cache(self):
        tmp = self.cache_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.cache, f, indent=1)
        os.replace(tmp, self.cache_path)

    @staticmethod
    def hex_key(hex_path):
        h = hashlib.sha256()
        with open(hex_path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest() + "|" + CACHE_VERSION

    def classify(self, sp, rt):
        if sp is None:
            return "InvalidProgram", {}
        if sp.timed_out or (not sp.reached_stop and sp.n_commits >= 5_000_000):
            return "TimeoutNoDump", {"side": "spike"}
        if not sp.reached_stop:
            return "InvalidProgram", {"side": "spike", "error": sp.error}
        if rt is None:
            return "InvalidProgram", {"side": "rtl-not-run"}
        if rt.timed_out:
            return "TimeoutNoDump", {"side": "rtl"}
        if rt.passed is None:
            return "InvalidProgram", {"side": "rtl", "error": rt.error}

        sp_fields = rtlmod.parse_console(sp.console)
        rt_fields = rtlmod.parse_console(rt.console)
        full_mode = rt_fields["bug80"] or rt_fields["ok80"]
        epilogue_mode = not full_mode
        rt_rc = rtlmod.rc_from_console(rt_fields) if full_mode else (0 if rt.passed else 1)
        detail = {"spike_a0": sp.a0, "rtl_rc": rt_rc, "mode": "epilogue" if epilogue_mode else "full",
                  "spike_fields": sp_fields, "rtl_fields": rt_fields}

        chk_equal = True
        for key in ("chk_a", "chk_b"):
            if key in sp_fields and key in rt_fields:
                chk_equal &= (sp_fields[key] == rt_fields[key])
        detail["chk_equal"] = chk_equal

        diverged = (sp.a0 != rt_rc) or (
            "mcycleh" in sp_fields and "mcycleh" in rt_fields
            and sp_fields["mcycleh"] != rt_fields["mcycleh"]) or not chk_equal

        if not diverged and sp.a0 == 0 and rt.passed:
            return "NoBug", detail

        if epilogue_mode:
            sig_ok = (
                chk_equal
                and sp.a0 is not None and sp.a0 & 1 == 0
                and rt_rc & 1 == 1
                and sp.mcycleh_final in (0, None)
                and sp_fields.get("mcycleh", 0) == 0
                and ("mcycleh" not in rt_fields or rt_fields["mcycleh"] != 0)
                and sp.trigger_executed
                and EPILOGUE_MARKER in rt.console
                and EPILOGUE_MARKER in sp.console
            )
            return ("SameBug" if sig_ok else "OtherBug"), detail

        sig_ok = (
            chk_equal
            and sp.a0 is not None and sp.a0 & 1 == 0
            and rt_rc & 1 == 1
            and (sp.mcycleh_final in (0, None))
            and sp_fields.get("mcycleh", 0) == 0
            and rt_fields.get("bug80", False)
            and sp.trigger_executed
            and ("mcycleh" in rt_fields)
        )
        return ("SameBug" if sig_ok else "OtherBug"), detail

    def check(self, elf, hex_path, label=None, force=False, repeat=1):
        key = self.hex_key(hex_path)
        if self.use_cache and not force and key in self.cache:
            ent = self.cache[key]
            return OracleResult(ent["status"], cached=True,
                                detail=ent.get("detail", {}), runs=ent.get("runs", 1))
        if not os.path.exists(elf):
            return OracleResult("InvalidProgram", detail={"error": "elf missing: %s" % elf})

        statuses = []
        last = None
        run_dir_base = os.path.join(self.env.out, "runs",
                                    label or key[:12])
        for i in range(repeat):
            run_dir = run_dir_base if repeat == 1 else run_dir_base + "_%d" % i
            os.makedirs(run_dir, exist_ok=True)
            log_path = os.path.join(run_dir, "spike_commits.log") if self.save_spike_logs else None
            sp = spikemod.run_spike(elf, trigger_range=self.sig.trigger_range,
                                    timeout=self.spike_timeout, log_path=log_path)
            rt = None
            if sp.reached_stop:
                rt = rtlmod.run_rtl(self.env, hex_path, run_dir, timeout=self.rtl_timeout)
            status, detail = self.classify(sp, rt)
            statuses.append(status)
            last = OracleResult(status, spike=sp, rtl=rt, runs=i + 1, detail=detail)

        if len(set(statuses)) > 1:
            final = OracleResult("Nondeterminism", spike=last.spike, rtl=last.rtl,
                                 runs=repeat, detail={"statuses": statuses})
        else:
            final = last
            final.status = statuses[0]
        if self.use_cache and final.status != "Nondeterminism":
            self.cache[key] = {"status": final.status, "detail": final.detail,
                               "runs": repeat, "ts": time.time(),
                               "label": label, "elf": elf, "hex": hex_path}
            self._save_cache()
        return final
