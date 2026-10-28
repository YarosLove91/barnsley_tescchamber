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
from redlib.trace import Trace
from redlib.ctxsetter import (filter_csrs, gen_setter, find_call_main_pair,
                              find_data_end_pair, materialize_pair)
from redlib.epilogue import (gen_epilogue_min, stub_jal, trampoline_bytes)
from redlib.encode import T0, words_to_bytes
from redlib import encode as E

EP_ADDR = 0x3000
SETTER_VMA = 0x488000
SETTER_LMA = 0x8400
SETTER_CAP = 0x6000
RESTORE_BYTES_CAP = 4096
SKIP_REGIONS = [(0x490000, 0x491000), (0xF0000000, 0xF0001000)]


def find_trampoline_addr(ir):
    text = ir.sec_by_name[".text"]
    end = text["vma"] + text["size"]
    last = max((i for i in ir.instrs if i.section == ".text"), key=lambda i: i.addr)
    gap = end - (last.addr + last.size)
    if gap < 8:
        raise RuntimeError("no 8-byte tail padding in .text for trampoline")
    return end - 8


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=int, default=40)
    ap.add_argument("--smoke", action="store_true",
                    help="build anchor slices without oracle runs")
    args = ap.parse_args()

    env = Env()
    out = os.path.join(env.out, "phaseB")
    os.makedirs(out, exist_ok=True)
    ir = IR(env, env.base_elf)
    text = ir.sec_by_name[".text"]
    t_lo, t_hi = text["vma"], text["vma"] + text["size"]

    phase_a_path = os.path.join(env.out, "phaseA", "phaseA_report.json")
    with open(phase_a_path) as f:
        pa = json.load(f)
    c_star = pa["result"]["boundary_cut_commit0"]
    stub_addr = int(pa["result"]["stub_addr_at_boundary"], 16)
    fail_pc = int(pa["result"]["failing_pc"], 16)

    trace_path = os.path.join(env.out, "phaseA", "base_trace.log")
    t0 = time.monotonic()
    trace = Trace(trace_path)
    print("trace loaded: %d commits (%.1fs)" % (trace.n, time.monotonic() - t0))
    assert trace.n > c_star and trace.pcs[c_star] == fail_pc, "phase A boundary mismatch"

    def in_text(pc):
        return t_lo <= pc < t_hi

    de_addr, de_rd = find_data_end_pair(ir, ir.symbols["__DATA_END__"])
    cm_addr = find_call_main_pair(ir, ir.symbols["main"])
    tramp = find_trampoline_addr(ir)
    print("crt: __DATA_END__ pair @%#x (rd=x%d), call-main pair @%#x, tramp @%#x" % (
        de_addr, de_rd, cm_addr, tramp))

    first_text = next(i for i in range(trace.n) if in_text(trace.pcs[i]))
    p_main = first_text - 1
    print("main entry: commit %d (pc %#x), p_main=%d" % (first_text + 1, trace.pcs[first_text], p_main))

    sig = Signature80(ir.trigger_range())
    oracle = Oracle(env, sig)
    ep_bytes = gen_epilogue_min()

    report = {"c_star": c_star, "failing_pc": hex(fail_pc), "stub_addr": hex(stub_addr),
              "setter_vma": hex(SETTER_VMA), "setter_lma": hex(SETTER_LMA),
              "tramp": hex(tramp), "crt_data_end_pair": hex(de_addr),
              "crt_call_main": hex(cm_addr), "p_main": p_main,
              "probes": [], "rtl_runs": 0, "oracle_calls": 0}
    t_start = time.monotonic()

    def build_headcut(p, name):
        window_pc = trace.pcs[p + 1]
        if not in_text(window_pc):
            raise ValueError("window start %#x outside .text" % window_pc)
        restores = trace.window_readset(p, c_star, SKIP_REGIONS)
        if len(restores) > RESTORE_BYTES_CAP:
            raise ValueError("restore set too big: %d bytes" % len(restores))
        gpr = trace.gpr_state(p)
        csr = filter_csrs(trace.csr_state_filtered(p, cap=16))
        setter = gen_setter(restores, gpr, csr, window_pc, SETTER_VMA)
        if len(setter) > SETTER_CAP:
            raise ValueError("setter too big: %d bytes" % len(setter))
        new_end = SETTER_VMA + len(setter)
        if new_end > 0x48FC00:
            raise ValueError("setter overflows into stack: new_end=%#x" % new_end)
        sb = SliceBuild(env, env.base_elf)
        sb.add_extra(".epilogue", EP_ADDR, ep_bytes)
        sb.add_extra(".ctxsetter", SETTER_VMA, setter, lma=SETTER_LMA)
        sb.patch(tramp, trampoline_bytes(EP_ADDR))
        sb.patch(stub_addr, stub_jal(stub_addr, tramp))
        sb.patch(de_addr, words_to_bytes(materialize_pair(de_rd, new_end)))
        sb.patch(cm_addr, words_to_bytes(list(E.jump_imm(T0, SETTER_VMA))))
        art = sb.build(out, name)
        art.update(p=p, window_pc=window_pc, setter_len=len(setter),
                   n_restore=len(restores), n_csr=len(csr), new_end=new_end)
        return art

    def probe(p, tag):
        name = "cutB%07d" % p
        try:
            art = build_headcut(p, name)
        except ValueError as e:
            report["probes"].append({"p": p, "tag": tag, "status": "InvalidProgram",
                                     "error": str(e)})
            print("probe p=%d (%s): InvalidProgram (%s)" % (p, tag, e))
            return "InvalidProgram"
        report["oracle_calls"] += 1
        res = oracle.check(art["elf"], art["hex"], label=name)
        if res.rtl is not None and not res.cached:
            report["rtl_runs"] += 1
        entry = {"p": p, "tag": tag, "window_pc": hex(art["window_pc"]),
                 "setter_len": art["setter_len"], "n_restore": art["n_restore"],
                 "n_csr": art["n_csr"], "status": res.status, "cached": res.cached,
                 "spike_wall": round(res.spike.wall, 2) if res.spike else None,
                 "rtl_wall": round(res.rtl.wall, 2) if res.rtl else None}
        report["probes"].append(entry)
        print("probe p=%d window=%#x setter=%dB restore=%dB csr=%d: %s%s" % (
            p, art["window_pc"], art["setter_len"], art["n_restore"], art["n_csr"],
            res.status, " [cached]" if res.cached else ""))
        if report["rtl_runs"] > args.budget:
            raise RuntimeError("RTL budget %d exceeded" % args.budget)
        return res.status

    p_hi = c_star - 1
    if args.smoke:
        for p, tag in ((p_main, "lo"), (p_hi, "hi")):
            art = build_headcut(p, "smoke_%s" % tag)
            print("smoke %s: p=%d window=%#x setter=%dB restore=%dB csr=%d elf=%s" % (
                tag, p, art["window_pc"], art["setter_len"], art["n_restore"],
                art["n_csr"], art["elf"]))
        print("SMOKE_OK")
        _dump(out, report)
        return 0

    st_hi = probe(p_hi, "hi")
    if st_hi == "SameBug":
        p_star, st_lo = p_hi, None
    else:
        st_lo = probe(p_main, "lo")
        if st_lo != "SameBug":
            print("FATAL: neither anchor is SameBug (lo=%s hi=%s) — нужен history-fallback"
                  % (st_lo, st_hi))
            report["fatal"] = "no SameBug anchor"
            _dump(out, report)
            return 2
        l, r = p_main, p_hi
        while r - l > 1:
            mid = (l + r) // 2
            if probe(mid, "bisect") == "SameBug":
                l = mid
            else:
                r = mid
        p_star = l

    trig_start = ir.symbols["ml_trigger_start"]
    p_trig = next((p for p in range(c_star) if trace.pcs[p + 1] == trig_start), None)
    st_trig = probe(p_trig, "tz-core") if p_trig is not None else None

    final = build_headcut(p_star, "phaseB_final")
    report["result"] = {
        "p_star": p_star,
        "window_pc": hex(trace.pcs[p_star + 1]),
        "window_commits": c_star - p_star,
        "head_commits_removed": p_star - p_main + 1,
        "setter_len": final["setter_len"],
        "n_restore": final["n_restore"],
        "n_csr": final["n_csr"],
        "final_elf": final["elf"], "final_hex": final["hex"],
        "tz_core": {"p": p_trig, "status": st_trig} if p_trig is not None else None,
    }
    report["wall_seconds"] = round(time.monotonic() - t_start, 1)
    report["budget_ok"] = report["rtl_runs"] <= args.budget

    print()
    print("pillar p* = %d (window start %#x, window commits %d)" % (
        p_star, trace.pcs[p_star + 1], c_star - p_star))
    print("head removed: %d app commits (crt ~%d commits remain)" % (
        p_star - p_main + 1, p_main + 1))
    print("final setter: %d bytes, restore %d bytes, csr %d" % (
        final["setter_len"], final["n_restore"], final["n_csr"]))
    print("tz-core variant: p=%s status=%s" % (p_trig, st_trig))
    print("oracle calls=%d rtl_runs=%d wall=%.1fs budget_ok=%s" % (
        report["oracle_calls"], report["rtl_runs"], report["wall_seconds"],
        report["budget_ok"]))
    _dump(out, report)
    return 0


def _dump(out, report):
    path = os.path.join(out, "phaseB_report.json")
    with open(path, "w") as f:
        json.dump(report, f, indent=1)
    print("report:", path)


if __name__ == "__main__":
    sys.exit(main())
