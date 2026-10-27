import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from redlib.env import Env
from redlib.ir import IR
from redlib.oracle import Oracle, Signature80
from redlib.slicer import SliceBuild
from redlib.spike import run_spike
from redlib import epilogue as epi

EP_ADDR = 0x3000


def find_trampoline_addr(ir):
    text = ir.sec_by_name[".text"]
    end = text["vma"] + text["size"]
    last = max((i for i in ir.instrs if i.section == ".text"), key=lambda i: i.addr)
    gap = end - (last.addr + last.size)
    if gap < 8:
        raise RuntimeError("no 8-byte tail padding in .text for trampoline (gap=%d)" % gap)
    return end - 8


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=int, default=40)
    args = ap.parse_args()

    env = Env()
    out = os.path.join(env.out, "phaseA")
    os.makedirs(out, exist_ok=True)
    ir = IR(env, env.base_elf)
    n = len(ir.instrs)
    by_addr = {}
    for ins in ir.instrs:
        by_addr.setdefault(ins.addr, ins)
    trig_start, trig_end = ir.trigger_range()
    trig_i = ir.index_of(trig_start)
    print("IR: n=%d trigger=%#x..%#x idx0=%d" % (n, trig_start, trig_end, trig_i))

    t_start = time.monotonic()
    print("collecting base trace (spike)...")
    base_sp = run_spike(env.base_elf, trigger_range=(trig_start, trig_end),
                        timeout=600.0, log_path=os.path.join(out, "base_trace.log"),
                        collect_trace=True)
    if not base_sp.reached_stop:
        print("FATAL: base spike run did not reach 0xF8")
        return 2
    trace = base_sp.trace
    print("base trace: %d commits, first_trigger=%s (%.1fs)" % (
        base_sp.n_commits, base_sp.first_trigger_commit, base_sp.wall))

    first = [False] * len(trace)
    seen = set()
    for i, pc in enumerate(trace):
        if pc not in seen:
            seen.add(pc)
            first[i] = True

    cands = []
    for c in range(len(trace) - 1):
        d = c + 1
        if not first[d]:
            continue
        ins = by_addr.get(trace[d])
        if ins is None or ins.section != ".text" or ins.size != 4:
            continue
        cands.append(c)
    print("valid cut candidates: %d (of %d commits)" % (len(cands), len(trace)))
    if len(cands) < 2:
        print("FATAL: not enough candidates")
        return 2

    sig = Signature80((trig_start, trig_end))
    oracle = Oracle(env, sig)
    ep_bytes = epi.gen_epilogue_min()
    tramp_addr = find_trampoline_addr(ir)
    with open(os.path.join(out, "epilogue_min.bin"), "wb") as f:
        f.write(ep_bytes)

    report = {"ep_addr": hex(EP_ADDR), "tramp_addr": hex(tramp_addr),
              "n_instrs": n, "n_commits": base_sp.n_commits,
              "first_trigger_commit": base_sp.first_trigger_commit,
              "trigger": [hex(trig_start), hex(trig_end)],
              "n_candidates": len(cands),
              "probes": [], "rtl_runs": 0, "oracle_calls": 0}

    def make_slice(c):
        stub_addr = trace[c + 1]
        sb = SliceBuild(env, env.base_elf)
        sb.add_extra(".epilogue", EP_ADDR, ep_bytes)
        sb.patch(tramp_addr, epi.trampoline_bytes(EP_ADDR))
        sb.patch(stub_addr, epi.stub_jal(stub_addr, tramp_addr))
        art = sb.build(out, "cutd%07d" % c)
        art["cut_commit"] = c
        art["stub_addr"] = stub_addr
        return art

    def probe(ci):
        c = cands[ci]
        art = make_slice(c)
        report["oracle_calls"] += 1
        res = oracle.check(art["elf"], art["hex"], label="cutd%07d" % c)
        if res.rtl is not None and not res.cached:
            report["rtl_runs"] += 1
        stub_ins = by_addr[art["stub_addr"]]
        entry = {"cand_i": ci, "cut_commit0": c, "commit1": c + 1,
                 "stub_addr": hex(art["stub_addr"]),
                 "last_kept_pc": hex(trace[c]),
                 "status": res.status, "cached": res.cached,
                 "spike_wall": round(res.spike.wall, 2) if res.spike else None,
                 "rtl_wall": round(res.rtl.wall, 2) if res.rtl else None}
        report["probes"].append(entry)
        print("probe commit=%d last_kept=%#x stub@%#x (%s): %s%s" % (
            c + 1, trace[c], art["stub_addr"], stub_ins.text.split()[0],
            res.status, " [cached]" if res.cached else ""))
        if report["rtl_runs"] > args.budget:
            raise RuntimeError("RTL budget %d exceeded" % args.budget)
        return res.status

    lo, hi = 0, len(cands) - 1
    st_lo = probe(lo)
    st_hi = probe(hi)
    report["invariant_init"] = {"lo_cand": cands[lo], "lo_status": st_lo,
                                "hi_cand": cands[hi], "hi_status": st_hi}
    if st_lo == "SameBug":
        print("FATAL: left anchor is SameBug — инвариант не установлен")
        report["fatal"] = "left anchor SameBug"
        _dump(out, report)
        return 2
    if st_hi != "SameBug":
        print("FATAL: right anchor is not SameBug (%s)" % st_hi)
        report["fatal"] = "right anchor %s" % st_hi
        _dump(out, report)
        return 2

    while hi - lo > 1:
        mid = (lo + hi) // 2
        if probe(mid) == "SameBug":
            hi = mid
        else:
            lo = mid

    c_star = cands[hi]
    fail_pc = trace[c_star]
    fail_ins = by_addr[fail_pc]
    c_prev = cands[lo]
    report["result"] = {
        "boundary_cut_commit0": c_star,
        "boundary_commit1": c_star + 1,
        "failing_pc": hex(fail_pc),
        "failing_static_k": fail_ins.idx - 1,
        "failing_static_idx1": fail_ins.idx,
        "failing_enc": "%0*x" % (fail_ins.size * 2, fail_ins.enc),
        "failing_text": fail_ins.text,
        "last_ok_cut_commit0": c_prev,
        "stub_addr_at_boundary": hex(trace[c_star + 1]),
        "boundary_slice": os.path.join(out, "cutd%07d.elf" % c_star),
    }
    report["wall_seconds"] = round(time.monotonic() - t_start, 1)
    report["budget_ok"] = report["rtl_runs"] <= args.budget

    print()
    print("failing dynamic instruction: commit %d  pc %#x  [%d] %0*x  %s" % (
        c_star + 1, fail_pc, fail_ins.idx - 1, fail_ins.size * 2, fail_ins.enc, fail_ins.text))
    print("stub at next commit          : pc %#x" % trace[c_star + 1])
    print("oracle calls=%d rtl_runs=%d wall=%.1fs budget_ok=%s" % (
        report["oracle_calls"], report["rtl_runs"], report["wall_seconds"], report["budget_ok"]))
    _dump(out, report)
    return 0 if report["budget_ok"] else 1


def _dump(out, report):
    path = os.path.join(out, "phaseA_report.json")
    with open(path, "w") as f:
        json.dump(report, f, indent=1)
    print("report:", path)


if __name__ == "__main__":
    sys.exit(main())
