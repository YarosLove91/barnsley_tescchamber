import argparse
import hashlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from redlib.env import Env, sh
from redlib.ir import IR
from redlib.oracle import Oracle, SignatureSum, extract_sum
from redlib.slicer import SliceBuild
from redlib.trace import Trace
from redlib.ctxsetter import gen_setter
from redlib.epilogue import stub_jal
from redlib.spike import run_spike
from redlib.binutils import full_dump, to_verilog_hex
from redlib.encode import (A0, A1, NOP, T2, T3, T4, T5, X0, addi, andi, jal, jr,
                           li_small, lui, sb, srli, words_to_bytes)

OUTPORT_HI = 0xF0000
SUM_REG = A1
EP_ADDR = 0x3000
SETTER_ADDR = 0x4000
NOP4 = NOP.to_bytes(4, "little")
SKIP_REGIONS = [(0xF0000000, 0xF0001000)]

ADDBUG_S = r"""
.option norvc
.section .text
.globl _start
.globl poison_add
_start:
    li   a1, 0
    li   t1, 0xA50
    .rept 16
    add  a1, a1, t1
    .endr
    li   t1, 0x37
poison_add:
    add  a1, a1, t1
    add  a1, a1, t1
    add  a1, a1, t1
    lui  t2, 0xf0000
    li   t3, 0x53
    sb   t3, 0(t2)
    srli t4, a1, 24
    srli t5, t4, 4
    andi t5, t5, 0xF
    addi t5, t5, 0x30
    sb   t5, 0(t2)
    andi t4, t4, 0xF
    addi t4, t4, 0x30
    sb   t4, 0(t2)
    srli t4, a1, 16
    srli t5, t4, 4
    andi t5, t5, 0xF
    addi t5, t5, 0x30
    sb   t5, 0(t2)
    andi t4, t4, 0xF
    addi t4, t4, 0x30
    sb   t4, 0(t2)
    srli t4, a1, 8
    srli t5, t4, 4
    andi t5, t5, 0xF
    addi t5, t5, 0x30
    sb   t5, 0(t2)
    andi t4, t4, 0xF
    addi t4, t4, 0x30
    sb   t4, 0(t2)
    andi t4, a1, 0xFF
    srli t5, t4, 4
    andi t5, t5, 0xF
    addi t5, t5, 0x30
    sb   t5, 0(t2)
    andi t4, t4, 0xF
    addi t4, t4, 0x30
    sb   t4, 0(t2)
    li   t5, 0xA5A5
    sub  a0, a1, t5
    snez a0, a0
    addi t4, a0, 0x30
    sb   t4, 0(t2)
    li   t5, 0xf4
    jr   t5
"""

ADDBUG_LD = r"""
OUTPUT_ARCH("riscv")
ENTRY(_start)
MEMORY { RAM (rwx) : ORIGIN = 0x0, LENGTH = 64K }
SECTIONS {
  .text 0x0 : {
    . = 0xF4; LONG(0x13); LONG(0x6F); LONG(-1);
    . = 0x200;
    *(.text)
  } >RAM
}
"""


def _emit_sum_byte(shift):
    if shift:
        w = [srli(T4, SUM_REG, shift)]
    else:
        w = [andi(T4, SUM_REG, 0xFF)]
    w += [srli(T5, T4, 4), andi(T5, T5, 0xF), addi(T5, T5, 0x30), sb(T5, 0, T2)]
    w += [andi(T4, T4, 0xF), addi(T4, T4, 0x30), sb(T4, 0, T2)]
    return w


def gen_demo_epilogue():
    words = [
        lui(T2, OUTPORT_HI),
        li_small(T3, ord("S")),
        sb(T3, 0, T2),
    ]
    for sh in (24, 16, 8, 0):
        words += _emit_sum_byte(sh)
    words += [
        li_small(A0, 0),
        li_small(T5, 0xF4),
        jr(T5),
    ]
    return words_to_bytes(words)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=int, default=120)
    args = ap.parse_args()

    env = Env()
    out = os.path.join(env.out, "demo_addbug")
    os.makedirs(out, exist_ok=True)
    report = {"rtl_runs": 0, "oracle_calls": 0, "stages": {}}
    t_start = time.monotonic()
    rtl_runs = [0]

    s_path = os.path.join(out, "addbug.S")
    ld_path = os.path.join(out, "addbug.ld")
    with open(s_path, "w") as f:
        f.write(ADDBUG_S)
    with open(ld_path, "w") as f:
        f.write(ADDBUG_LD)
    elf = os.path.join(out, "addbug.elf")
    hexf = os.path.join(out, "addbug.hex")
    sh([env.tool("gcc"), "-nostartfiles", "-nostdlib",
        "-march=rv32imc_zicsr_zifencei", "-mabi=ilp32",
        "-T", ld_path, s_path, "-o", elf])
    to_verilog_hex(env, elf, hexf)
    dump = full_dump(env, elf, os.path.join(out, "addbug.dump"))

    ir = IR(env, elf)
    poison = ir.symbols["poison_add"]
    by_addr = {}
    for ins in ir.instrs:
        by_addr.setdefault(ins.addr, ins)
    text = ir.sec_by_name[".text"]
    code_end = text["vma"] + text["size"]
    print("base built: %d instrs, poison_add @%#x, code [%#x..%#x)" % (
        len(ir.instrs), poison, 0x200, code_end))
    report["stages"]["base"] = {"n_instrs": len(ir.instrs), "poison_add": hex(poison)}

    sig = SignatureSum((poison, poison + 4))
    oracle = Oracle(env, sig, cache_path=os.path.join(out, "oracle_cache.json"))

    def probe(art_elf, art_hex, label):
        report["oracle_calls"] += 1
        res = oracle.check(art_elf, art_hex, label=label)
        if res.rtl is not None and not res.cached:
            rtl_runs[0] += 1
        if rtl_runs[0] > args.budget:
            raise RuntimeError("RTL budget exceeded")
        return res

    res = probe(elf, hexf, "addbug_base")
    d = res.detail
    print("BASE differential: %s  spike_sum=%s rtl_sum=%s spike_a0=%s rtl_passed=%s commits=%s" % (
        res.status,
        hex(d["spike_sum"]) if d.get("spike_sum") is not None else None,
        hex(d["rtl_sum"]) if d.get("rtl_sum") is not None else None,
        d.get("spike_a0"), d.get("rtl_passed"), res.spike_commits))
    report["stages"]["base_diff"] = {"status": res.status, "detail": d,
                                     "commits": res.spike_commits}
    if res.status != "SameBug":
        print("FATAL: базовая программа не демонстрирует расхождение — RTL-баг не.injected?")
        _dump(out, report)
        return 2

    sp = run_spike(elf, trigger_range=sig.trigger_range, collect_trace=True,
                   timeout=60, log_path=os.path.join(out, "base_trace.log"))
    assert sp.reached_stop, "base spike run failed"
    pcs = sp.trace
    n = len(pcs)
    first = [False] * n
    seen = set()
    for i, pc in enumerate(pcs):
        if pc not in seen:
            seen.add(pc)
            first[i] = True
    cands = [c for c in range(n - 1)
             if first[c + 1] and 0x200 <= pcs[c + 1] < code_end
             and pcs[c + 1] not in (0xF4, 0xF8)
             and by_addr.get(pcs[c + 1]) is not None
             and by_addr[pcs[c + 1]].size == 4]
    print("trace: %d commits, poison executed at %d; tail candidates: %d" % (
        n, sp.first_trigger_commit, len(cands)))
    report["stages"]["trace"] = {"commits": n,
                                 "first_poison_commit": sp.first_trigger_commit,
                                 "n_candidates": len(cands)}

    ep_bytes = gen_demo_epilogue()
    with open(os.path.join(out, "epilogue.bin"), "wb") as f:
        f.write(ep_bytes)

    def build_tail(c, name):
        sb = SliceBuild(env, elf)
        sb.add_extra(".epilogue", EP_ADDR, ep_bytes)
        sb.patch(pcs[c + 1], stub_jal(pcs[c + 1], EP_ADDR))
        return sb.build(out, name)

    def tail_probe(ci):
        c = cands[ci]
        art = build_tail(c, "addbug_tailA%04d" % c)
        res = probe(art["elf"], art["hex"], "addbug_tailA%04d" % c)
        print("  tail probe c=%d (stub@%#x): %s" % (c, pcs[c + 1], res.status))
        return res.status

    lo, hi = 0, len(cands) - 1
    st_lo, st_hi = tail_probe(lo), tail_probe(hi)
    if st_lo == "SameBug" or st_hi != "SameBug":
        print("FATAL: tail anchors invalid (lo=%s hi=%s)" % (st_lo, st_hi))
        report["fatal"] = "tail anchors lo=%s hi=%s" % (st_lo, st_hi)
        _dump(out, report)
        return 2
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if tail_probe(mid) == "SameBug":
            hi = mid
        else:
            lo = mid
    c_star = cands[hi]
    fail_pc = pcs[c_star]
    print("TAIL RESULT: failing commit %d (1-based %d), pc=%#x — %s" % (
        c_star, c_star + 1, fail_pc, by_addr[fail_pc].text))
    report["stages"]["tail"] = {
        "c_star": c_star, "failing_pc": hex(fail_pc),
        "failing_is_poison_add": fail_pc == poison,
        "expected_pc": hex(poison)}

    trace = Trace(os.path.join(out, "base_trace.log"))
    assert trace.n == n

    p_star = c_star - 1
    window_pc = pcs[p_star + 1]
    restores = trace.window_readset(p_star, c_star, SKIP_REGIONS)
    gpr = trace.gpr_state(p_star)
    setter0 = gen_setter(restores, gpr, [], window_pc, SETTER_ADDR)
    n_words = len(setter0) // 4
    print("HEAD: p*=%d window=%#x setter=%dB restore=%dB (%d words)" % (
        p_star, window_pc, len(setter0), len(restores), n_words))

    def build_head(nopped, window_nop, name):
        sb_bytes = bytearray(setter0)
        for w in sorted(nopped):
            sb_bytes[w * 4:w * 4 + 4] = NOP4
        sb = SliceBuild(env, elf)
        sb.add_extra(".epilogue", EP_ADDR, ep_bytes)
        sb.add_extra(".ctxsetter", SETTER_ADDR, bytes(sb_bytes))
        sb.patch(0x200, words_to_bytes([jal(X0, SETTER_ADDR - 0x200)]))
        sb.patch(pcs[c_star + 1], stub_jal(pcs[c_star + 1], EP_ADDR))
        if window_nop:
            sb.patch(window_pc, NOP4)
        return sb.build(out, name)

    def head_probe(nopped, window_nop, tag):
        h = hashlib.sha1(repr((sorted(nopped), window_nop)).encode()).hexdigest()[:10]
        name = "addbug_head_%s" % h
        art = build_head(nopped, window_nop, name)
        res = probe(art["elf"], art["hex"], name)
        print("  head probe %s (nopped=%d, win_nop=%s): %s" % (
            tag, len(nopped), window_nop, res.status))
        return res.status, art

    st, _ = head_probe(set(), False, "full")
    if st != "SameBug":
        print("FATAL: head-cut slice is %s" % st)
        report["fatal"] = "head-cut %s" % st
        _dump(out, report)
        return 2

    items = list(range(n_words - 1)) + ["win"]
    nopped = set()
    changed = True
    passes = 0
    while changed and passes < 3:
        changed = False
        passes += 1
        for it in items:
            if it in nopped:
                continue
            trial = nopped | {it}
            wn = "win" in trial
            words = {x for x in trial if x != "win"}
            st, _ = head_probe(words, wn, "ddmin p%d %s" % (passes, it))
            if st == "SameBug":
                nopped = trial
                changed = True

    final_words = {x for x in nopped if x != "win"}
    window_nopped = "win" in nopped
    st_final, art_final = head_probe(final_words, window_nopped, "final")
    st_small, art_small = head_probe(final_words, True, "smaller")

    essential = [w for w in range(n_words - 1) if w not in nopped]
    report["stages"]["head_ddmin"] = {
        "p_star": p_star, "window_pc": hex(window_pc),
        "setter_words": n_words, "essential_words": essential,
        "nop_count": len(nopped), "window_nopped_by_ddmin": window_nopped,
        "final_status": st_final, "smaller_status": st_small,
        "final_elf": art_final["elf"], "final_hex": art_final["hex"],
        "final_dump": art_final["dump"],
        "smaller_elf": art_small["elf"],
    }

    res_final = probe(art_final["elf"], art_final["hex"], "addbug_final_check")
    commits_final = res_final.spike_commits
    core_instrs = len(essential) + 1 + (0 if window_nopped else 1) + 1 + len(ep_bytes) // 4 + 1
    report["metrics"] = {
        "baseline_commits": n,
        "final_commits": commits_final,
        "dynamic_reduction_pct": round(100.0 * (1 - (commits_final or 0) / n), 3),
        "core_instrs_approx": core_instrs,
        "contrast": {"larger": st_final, "smaller": st_small},
        "rtl_runs_total": rtl_runs[0],
        "oracle_calls": report["oracle_calls"],
    }
    report["wall_seconds"] = round(time.monotonic() - t_start, 1)
    ok = (report["stages"]["tail"]["failing_is_poison_add"]
          and st_final == "SameBug" and st_small == "NoBug")
    report["demo_accepted"] = ok

    print()
    print("=== DEMO ADDBUG SUMMARY ===")
    print("failing instruction : pc=%#x (%s) — метка poison_add: %s" % (
        fail_pc, by_addr[fail_pc].text, fail_pc == poison))
    print("final core: setter essential words=%s + window + stub + epilogue(%d) ≈ %d instrs" % (
        essential, len(ep_bytes) // 4, core_instrs))
    print("dynamics: %d -> %s commits (-%s%%)" % (
        n, commits_final, report["metrics"]["dynamic_reduction_pct"]))
    print("contrast: larger=%s smaller=%s" % (st_final, st_small))
    print("rtl_runs=%d/%d wall=%.1fs" % (rtl_runs[0], args.budget, report["wall_seconds"]))
    print("DEMO:", "OK" if ok else "FAIL")
    _dump(out, report)
    return 0 if ok else 1


def _dump(out, report):
    report["rtl_runs"] = report.get("stages") and report.get("rtl_runs", 0)
    path = os.path.join(out, "demo_addbug_report.json")
    with open(path, "w") as f:
        json.dump(report, f, indent=1)
    print("report:", path)


if __name__ == "__main__":
    sys.exit(main())
