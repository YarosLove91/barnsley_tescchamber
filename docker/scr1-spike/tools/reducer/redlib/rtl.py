import os
import re
import shutil
import subprocess
import time

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
FORBIDDEN_NAME_SUBSTRINGS = ("compliance", "arch")


class RtlResult:
    def __init__(self):
        self.ok = False
        self.timed_out = False
        self.passed = None
        self.results_line = None
        self.console = ""
        self.wall = None
        self.error = None
        self.log_path = None

    def to_dict(self):
        return {k: v for k, v in self.__dict__.items()}


def parse_console(text):
    fields = {}
    for key in ("chk_a", "chk_b", "checksum", "mcycle", "mcycleh"):
        m = re.search(re.escape(key) + r"\s*=\s*0x([0-9a-fA-F]{8})(?![0-9a-fA-F])", text)
        if m:
            fields[key] = int(m.group(1), 16)
    fields["bug80"] = "BUG #80 reproduced" in text
    fields["ok80"] = "OK: mcycleh unchanged" in text
    fields["chk_mismatch"] = "CHECKSUM A MISMATCH" in text or "CHECKSUM B MISMATCH" in text
    return fields


def rc_from_console(fields):
    rc = 0
    if fields.get("bug80"):
        rc |= 1
    if fields.get("chk_mismatch"):
        rc |= 2
    return rc


def run_rtl(env, hex_path, run_dir, timeout=300.0, imem="FFFFFFFF", dmem="FFFFFFFF"):
    r = RtlResult()
    name = os.path.basename(hex_path)
    low = name.lower()
    for bad in FORBIDDEN_NAME_SUBSTRINGS:
        if bad in low:
            raise ValueError("hex name %r contains %r (tb identify_test would treat it "
                             "as signature test)" % (name, bad))
    os.makedirs(run_dir, exist_ok=True)
    dst = os.path.join(run_dir, name)
    shutil.copyfile(hex_path, dst)
    info = os.path.join(run_dir, "test_info")
    results = os.path.join(run_dir, "test_results.txt")
    with open(info, "w") as f:
        f.write(name + "\n")
    for stale in (results,):
        if os.path.exists(stale):
            os.remove(stale)
    cmd = [env.v_bin,
           "+test_info=" + info,
           "+test_results=" + results,
           "+imem_pattern=" + imem,
           "+dmem_pattern=" + dmem]
    log_path = os.path.join(run_dir, "rtl_stdout.log")
    t0 = time.monotonic()
    try:
        p = subprocess.run(cmd, cwd=run_dir, capture_output=True, text=True, timeout=timeout)
        stdout = p.stdout
        r.error = None if p.returncode == 0 else "exit=%d %s" % (p.returncode, p.stderr[-2000:])
    except subprocess.TimeoutExpired as e:
        stdout = (e.stdout or b"").decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        r.timed_out = True
        r.error = "wall timeout %.0fs" % timeout
    r.wall = time.monotonic() - t0
    clean = ANSI_RE.sub("", stdout)
    with open(log_path, "w") as f:
        f.write(clean)
    r.log_path = log_path
    r.console = clean
    if "Error: TIMEOUT" in clean:
        r.timed_out = True
    if os.path.exists(results):
        with open(results) as f:
            lines = [l for l in f.read().splitlines() if l.strip()]
        if lines:
            r.results_line = lines[-1]
            parts = [x for x in re.split(r"\s+", r.results_line) if x]
            if len(parts) >= 3:
                r.passed = (parts[1] == "OK" and parts[2] == "PASS")
    r.ok = r.passed is not None and not r.timed_out
    return r
