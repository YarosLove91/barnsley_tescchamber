import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from redlib.env import Env
from redlib.ir import IR
from redlib.oracle import Oracle, Signature80
from redlib.slicer import SliceBuild, same_bytes
from redlib import binutils

GROUND_TRUTH = {
    "static_total": 3370,
    "trigger_start": 0x004820EE,
    "trigger_end": 0x0048211A,
    "trigger_static_idx": 2924,
    "spike_commits": 336694,
    "first_trigger_commit": 200971,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()

    env = Env()
    out = os.path.join(env.out, "phase0")
    os.makedirs(out, exist_ok=True)
    print("WT       =", env.wt)
    print("SCR1_DIR =", env.scr1_dir)
    print("BLD      =", env.bld)
    print("OUT      =", out)

    report = {"ground_truth_expected": {k: (hex(v) if isinstance(v, int) and v > 4096 else v)
                                        for k, v in GROUND_TRUTH.items()}}

    t0 = time.monotonic()
    ir = IR(env, env.base_elf)
    summ = ir.summary()
    report["ir_summary"] = {k: (hex(v) if isinstance(v, int) and v > 4096 else v)
                            for k, v in summ.items() if k != "sections"}
    report["ir_sections"] = {k: {kk: (hex(vv) if isinstance(vv, int) else vv) for kk, vv in v.items()}
                             for k, v in summ["sections"].items()}
    report["ir_build_seconds"] = round(time.monotonic() - t0, 2)
    print("IR: static_total=%d trigger=%#x..%#x idx=%s entry=%#x (%.1fs)" % (
        summ["static_total"], summ["trigger_start"], summ["trigger_end"],
        summ["trigger_static_idx"], summ["entry"], report["ir_build_seconds"]))

    gt_ok = (summ["static_total"] == GROUND_TRUTH["static_total"]
             and summ["trigger_start"] == GROUND_TRUTH["trigger_start"]
             and summ["trigger_end"] == GROUND_TRUTH["trigger_end"]
             and summ["trigger_static_idx"] == GROUND_TRUTH["trigger_static_idx"])
    report["ground_truth_static_ok"] = gt_ok
    print("ground truth static:", "OK" if gt_ok else "MISMATCH")
    if not gt_ok:
        print(json.dumps(summ, indent=1, default=str))

    sb = SliceBuild(env, env.base_elf)
    t0 = time.monotonic()
    art = sb.build(out, "idn")
    slice_seconds = time.monotonic() - t0
    base_hex = sb.base_hex(out)
    identical = same_bytes(art["hex"], base_hex)
    report["identity_slice"] = {
        "elf": art["elf"], "hex": art["hex"],
        "hex_identical_to_base": identical,
        "build_seconds": round(slice_seconds, 2),
        "sha256_hex": __import__("hashlib").sha256(open(art["hex"], "rb").read()).hexdigest(),
    }
    print("identity slice: hex_identical=%s (%.1fs)" % (identical, slice_seconds))
    if not identical:
        print("ERROR: identity slice hex differs from base hex")
        with open(art["hex"]) as fa, open(base_hex) as fb:
            la, lb = fa.read().splitlines(), fb.read().splitlines()
        for i, (x, y) in enumerate(zip(la, lb)):
            if x != y:
                print("first diff at line %d:\n  slice: %s\n  base : %s" % (i + 1, x, y))
                break
        print("lines: slice=%d base=%d" % (len(la), len(lb)))
        sys.exit(2)

    sig = Signature80(ir.trigger_range())
    oracle = Oracle(env, sig, use_cache=not args.no_cache)

    statuses = []
    for i in range(args.runs):
        t0 = time.monotonic()
        res = oracle.check(env.base_elf, os.path.join(env.bld, "mcycle_rtos.hex"),
                           label="full_run%d" % (i + 1), force=True)
        wall = time.monotonic() - t0
        statuses.append(res.status)
        sp, rt = res.spike, res.rtl
        entry = {"run": i + 1, "status": res.status, "wall": round(wall, 1),
                 "spike_wall": round(sp.wall, 1) if sp else None,
                 "rtl_wall": round(rt.wall, 1) if rt else None}
        if sp:
            entry.update({"commits": sp.n_commits, "spike_a0": sp.a0,
                          "first_trigger_commit": sp.first_trigger_commit,
                          "mcycleh_final": sp.mcycleh_final})
        if rt:
            entry.update({"rtl_passed": rt.passed})
        report.setdefault("oracle_runs", []).append(entry)
        print("oracle run %d: %s (spike %.1fs / rtl %.1fs) commits=%s a0=%s first_trig=%s" % (
            i + 1, res.status, sp.wall if sp else -1, rt.wall if rt else -1,
            sp.n_commits if sp else "?", sp.a0 if sp else "?",
            sp.first_trigger_commit if sp else "?"))

    report["statuses"] = statuses
    accept_oracle = statuses == ["SameBug"] * args.runs
    sp_run = report["oracle_runs"][-1]
    dyn_ok = (sp_run.get("commits") == GROUND_TRUTH["spike_commits"]
              and sp_run.get("first_trigger_commit") == GROUND_TRUTH["first_trigger_commit"])
    report["ground_truth_dynamic_ok"] = dyn_ok

    idn_key = Oracle.hex_key(art["hex"])
    idn_res = oracle.check(art["elf"], art["hex"], label="identity_slice")
    report["identity_slice_oracle"] = {"status": idn_res.status, "cached": idn_res.cached}
    print("identity slice oracle: %s (cached=%s)" % (idn_res.status, idn_res.cached))

    report["acceptance"] = {
        "static_ground_truth": gt_ok,
        "dynamic_ground_truth": dyn_ok,
        "identity_slice_hex_identical": identical,
        "oracle_samebug_x%d" % args.runs: accept_oracle,
    }
    ok = gt_ok and identical and accept_oracle and dyn_ok
    report["phase0_accepted"] = ok

    with open(os.path.join(out, "phase0_report.json"), "w") as f:
        json.dump(report, f, indent=1, default=str)
    print("report:", os.path.join(out, "phase0_report.json"))
    print("PHASE0_ACCEPT:", "OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
