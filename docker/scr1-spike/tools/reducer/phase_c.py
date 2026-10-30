import argparse
import hashlib
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from redlib.env import Env
from redlib.ir import IR
from redlib.oracle import Oracle, Signature80
from redlib.slicer import SliceBuild
from redlib.ctxsetter import find_call_main_pair, find_data_end_pair, materialize_pair
from redlib.epilogue import gen_epilogue_min, stub_jal, trampoline_bytes
from redlib.encode import NOP, T0, words_to_bytes
from redlib import encode as E

EP_ADDR = 0x3000
SETTER_VMA = 0x488000
SETTER_LMA = 0x8400
NOP4 = NOP.to_bytes(4, "little")


def find_trampoline_addr(ir):
    text = ir.sec_by_name[".text"]
    end = text["vma"] + text["size"]
    last = max((i for i in ir.instrs if i.section == ".text"), key=lambda i: i.addr)
    if end - (last.addr + last.size) < 8:
        raise RuntimeError("no tail padding for trampoline")
    return end - 8


def parse_ctx_disasm(dump_path):
    dis = {}
    pat = re.compile(r"^\s+([0-9a-f]+):\s+[0-9a-f]+\s+(\S.*\S)\s*$")
    with open(dump_path) as f:
        for line in f:
            m = pat.match(line)
            if m:
                dis[int(m.group(1), 16)] = m.group(2)
    return dis


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=int, default=80)
    ap.add_argument("--passes", type=int, default=3)
    args = ap.parse_args()

    env = Env()
    out = os.path.join(env.out, "phaseC")
    os.makedirs(out, exist_ok=True)
    ir = IR(env, env.base_elf)

    with open(os.path.join(env.out, "phaseA", "phaseA_report.json")) as f:
        pa = json.load(f)
    with open(os.path.join(env.out, "phaseB", "phaseB_report.json")) as f:
        pb = json.load(f)
    c_star = pa["result"]["boundary_cut_commit0"]
    stub_addr = int(pa["result"]["stub_addr_at_boundary"], 16)
    fail_pc = int(pa["result"]["failing_pc"], 16)
    p_star = pb["result"]["p_star"]

    setter0 = open(os.path.join(env.out, "phaseB", "phaseB_final.ctxsetter.bin"), "rb").read()
    n_words = len(setter0) // 4
    dis = parse_ctx_disasm(os.path.join(env.out, "phaseB", "phaseB_final.dump"))
    print("setter: %d bytes = %d words (last = JAL, protected); window pc=%#x" % (
        len(setter0), n_words, fail_pc))

    tramp = find_trampoline_addr(ir)
    de_addr, de_rd = find_data_end_pair(ir, ir.symbols["__DATA_END__"])
    cm_addr = find_call_main_pair(ir, ir.symbols["main"])
    ep_bytes = gen_epilogue_min()
    sig = Signature80(ir.trigger_range())
    oracle = Oracle(env, sig)

    items = [("setter", i) for i in range(n_words - 1)] + [("text", fail_pc)]

    report = {"p_star": p_star, "fail_pc": hex(fail_pc), "setter_words": n_words,
              "probes": [], "rtl_runs": 0, "oracle_calls": 0}
    t_start = time.monotonic()
    rtl_runs = [0]

    def build(nopped, name):
        sb_bytes = bytearray(setter0)
        win_nop = False
        for kind, v in nopped:
            if kind == "setter":
                sb_bytes[v * 4:v * 4 + 4] = NOP4
            else:
                win_nop = True
        sb = SliceBuild(env, env.base_elf)
        sb.add_extra(".epilogue", EP_ADDR, ep_bytes)
        sb.add_extra(".ctxsetter", SETTER_VMA, bytes(sb_bytes), lma=SETTER_LMA)
        sb.patch(tramp, trampoline_bytes(EP_ADDR))
        sb.patch(stub_addr, stub_jal(stub_addr, tramp))
        sb.patch(de_addr, words_to_bytes(materialize_pair(de_rd, SETTER_VMA + len(setter0))))
        sb.patch(cm_addr, words_to_bytes(list(E.jump_imm(T0, SETTER_VMA))))
        if win_nop:
            sb.patch(fail_pc, NOP4)
        return sb.build(out, name)

    def status_of(nopped, tag=""):
        frozen = tuple(sorted(nopped))
        h = hashlib.sha1(repr(frozen).encode()).hexdigest()[:10]
        name = "cutC_" + h
        art = build(frozen, name)
        report["oracle_calls"] += 1
        res = oracle.check(art["elf"], art["hex"], label=name)
        if res.rtl is not None and not res.cached:
            rtl_runs[0] += 1
        report["probes"].append({"tag": tag, "name": name, "n_nopped": len(frozen),
                                 "status": res.status, "cached": res.cached})
        if rtl_runs[0] > args.budget:
            raise RuntimeError("RTL budget %d exceeded" % args.budget)
        return res.status

    st0 = status_of(frozenset(), "baseline")
    print("baseline (phase B final): %s" % st0)
    if st0 != "SameBug":
        print("FATAL: baseline is not SameBug")
        report["fatal"] = "baseline %s" % st0
        _dump(out, report)
        return 2

    nopped = set()
    passes = 0
    changed = True
    while changed and passes < args.passes:
        changed = False
        passes += 1
        for it in items:
            if it in nopped:
                continue
            trial = nopped | {it}
            desc = ("setter.w%02d %s" % (it[1], dis.get(SETTER_VMA + 4 * it[1], "?"))
                    if it[0] == "setter" else "window %#x %s" % (it[1], dis.get(it[1], "?")))
            st = status_of(trial, "pass%d" % passes)
            if st == "SameBug":
                nopped = trial
                changed = True
                print("pass%d NOP  %-52s -> %s" % (passes, desc, st))
            else:
                print("pass%d KEEP %-52s -> %s" % (passes, desc, st))

    final = build(tuple(sorted(nopped)), "cutC_final")
    res_final = oracle.check(final["elf"], final["hex"], label="cutC_final")
    if res_final.rtl is not None and not res_final.cached:
        rtl_runs[0] += 1

    kept = [it for it in items if it not in nopped]
    core_words = n_words - len([1 for k, _ in nopped if k == "setter"])
    report["result"] = {
        "final_status": res_final.status,
        "nop_count": len(nopped),
        "kept_essential": [
            {"item": list(it),
             "dis": dis.get(SETTER_VMA + 4 * it[1] if it[0] == "setter" else it[1], "?")}
            for it in kept],
        "core_words_in_setter": core_words,
        "final_elf": final["elf"], "final_hex": final["hex"], "final_dump": final["dump"],
    }
    report["rtl_runs"] = rtl_runs[0]
    report["oracle_calls"] = report["oracle_calls"] + 1
    report["wall_seconds"] = round(time.monotonic() - t_start, 1)
    report["budget_ok"] = rtl_runs[0] <= args.budget

    print()
    print("ddmin: %d NOP'ed, %d essential kept:" % (len(nopped), len(kept)))
    for it in kept:
        d = dis.get(SETTER_VMA + 4 * it[1] if it[0] == "setter" else it[1], "?")
        print("   %-10s %s" % (("%s%d" % (it[0], it[1])) if it[0] == "setter" else hex(it[1]), d))
    print("final: %s (core setter words: %d + window 1 + stub/tramp/epilogue)" % (
        res_final.status, core_words))
    print("oracle calls=%d rtl_runs=%d wall=%.1fs budget_ok=%s" % (
        report["oracle_calls"], rtl_runs[0], report["wall_seconds"], report["budget_ok"]))
    _dump(out, report)
    return 0 if (res_final.status == "SameBug" and report["budget_ok"]) else 1


def _dump(out, report):
    path = os.path.join(out, "phaseC_report.json")
    with open(path, "w") as f:
        json.dump(report, f, indent=1)
    print("report:", path)


if __name__ == "__main__":
    sys.exit(main())
