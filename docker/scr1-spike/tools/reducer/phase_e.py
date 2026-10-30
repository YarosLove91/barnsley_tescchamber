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
from redlib.ctxsetter import find_call_main_pair, find_data_end_pair, materialize_pair
from redlib.encode import (A0, NOP, T0, T1, T2, X0, addi, csrr, csrrw, jal, jr,
                           jump_imm, li_small, lui, sb, words_to_bytes)

CORE_ADDR = 0x3000
OUTPORT_HI = 0xF0000
MARKER = ord("R")
CSR_MINSTRET = 0xB02
CSR_MINSTRETH = 0xB82
FAILING_ENC = 0xB0201073  # csrw minstret,zero (csrrw x0, 0xB02, x0)


def find_reloc_skip(ir, de_addr):
    init = [i for i in ir.instrs if i.section == ".text.init"]
    beq = None
    for ins in init:
        if ins.addr > de_addr and (ins.enc & 0x7F) == 0x63:
            beq = ins
            break
    if beq is None:
        raise RuntimeError("reloc-skip branch not found")
    target = None
    for ins in init:
        if ins.addr > beq.addr and ins.enc == 0xA0018613:
            target = ins.addr
            break
    if target is None or target - beq.addr > 64:
        raise RuntimeError("bss-start addi a2,gp not found")
    return beq.addr, target


def find_gp_init(ir):
    for ins in ir.instrs:
        if ins.section == ".text.init" and ins.addr >= 0x200 \
                and (ins.enc & 0x7F) == 0x17 and ((ins.enc >> 7) & 31) == 3:
            return ins.addr
    raise RuntimeError("gp init not found")


def gen_core(with_digit=True, failing_nop=False):
    words = [
        li_small(T0, -256),                 # t0 = 0xffffff00
        csrrw(X0, CSR_MINSTRET, T0),        # предусловие: minstret[31:8]=0xFFFFFF
        NOP if failing_nop else FAILING_ENC,  # csrw minstret,zero — виновная
        lui(T1, OUTPORT_HI),
        li_small(T2, MARKER),
        sb(T2, 0, T1),                      # маркер 'R'
        csrr(A0, CSR_MINSTRETH),            # a0 = rc = minstreth
    ]
    if with_digit:
        words += [addi(T2, A0, 48), sb(T2, 0, T1)]
    words += [li_small(T0, 0xF4), jr(T0)]
    return words_to_bytes(words)


def main():
    ap = argparse.ArgumentParser()
    args = ap.parse_args()

    env = Env()
    out = os.path.join(env.out, "phaseE")
    os.makedirs(out, exist_ok=True)
    ir = IR(env, env.base_elf)

    bss_end_addr, bss_rd = find_data_end_pair(ir, ir.symbols["__BSS_END__"])
    bss_start = ir.symbols.get("__BSS_START__", ir.sec_by_name[".sbss"]["vma"])
    cm_addr = find_call_main_pair(ir, ir.symbols["main"])
    de_addr, _ = find_data_end_pair(ir, ir.symbols["__DATA_END__"])
    beq_addr, skip_target = find_reloc_skip(ir, de_addr)
    gp_addr = find_gp_init(ir)

    sig = Signature80((CORE_ADDR, CORE_ADDR + 64))
    oracle = Oracle(env, sig)
    report = {"counter": "minstret", "core_addr": hex(CORE_ADDR),
              "failing_enc": "%08x" % FAILING_ENC,
              "variants": {}, "rtl_runs": 0}
    t_start = time.monotonic()

    def build_core(name, with_digit=True, failing_nop=False, skip_zero=True):
        core = gen_core(with_digit=with_digit, failing_nop=failing_nop)
        sb = SliceBuild(env, env.base_elf)
        sb.add_extra(".score", CORE_ADDR, core)
        sb.patch(beq_addr, words_to_bytes([jal(X0, skip_target - beq_addr)]))
        sb.patch(bss_end_addr, words_to_bytes(materialize_pair(bss_rd, bss_start)))
        sb.patch(cm_addr, words_to_bytes(list(jump_imm(T0, CORE_ADDR))))
        if skip_zero:
            sb.patch(0x200, words_to_bytes([jal(X0, gp_addr - 0x200)]))
        return sb.build(out, name), len(core) // 4

    def probe(art, tag, core_words):
        res = oracle.check(art["elf"], art["hex"], label=tag)
        if res.rtl is not None and not res.cached:
            report["rtl_runs"] += 1
        v = {"status": res.status, "cached": res.cached, "core_words": core_words,
             "spike_commits": res.spike_commits,
             "spike_a0": res.spike.a0 if res.spike else None,
             "spike_console": res.spike.console if res.spike else None,
             "elf": art["elf"], "hex": art["hex"], "dump": art["dump"]}
        report["variants"][tag] = v
        print("%-12s: %s (commits=%s a0=%s console=%r)%s" % (
            tag, res.status, v["spike_commits"], v["spike_a0"],
            v["spike_console"], " [cached]" if res.cached else ""))
        return res

    art, w = build_core("cutE_min")
    r_min = probe(art, "E_min", w)
    if r_min.status != "SameBug":
        print("FATAL: E_min is %s" % r_min.status)
        report["fatal"] = "E_min %s" % r_min.status
        _dump(out, report)
        return 2

    art, w = build_core("cutE_smaller", failing_nop=True)
    r_s = probe(art, "E_smaller", w)

    report["metrics"] = {
        "final_commits": r_min.spike_commits,
        "core_words": w,
        "contrast_pair": {
            "larger": "cutE_min (SameBug, виновная csrw minstret,zero на месте)",
            "smaller": "cutE_smaller (виновная csrw → NOP)",
            "smaller_status": r_s.status,
            "diff": "единственная инструкция csrw minstret,zero (b0201073)",
        },
    }
    report["wall_seconds"] = round(time.monotonic() - t_start, 1)
    ok = r_min.status == "SameBug" and r_s.status == "NoBug"
    report["phaseE_accepted"] = ok
    print()
    print("minstret core: %d words @%#x, %s коммитов" % (w, CORE_ADDR, r_min.spike_commits))
    print("PHASE_E:", "OK" if ok else "FAIL")
    _dump(out, report)
    return 0 if ok else 1


def _dump(out, report):
    path = os.path.join(out, "phaseE_report.json")
    with open(path, "w") as f:
        json.dump(report, f, indent=1)
    print("report:", path)


if __name__ == "__main__":
    sys.exit(main())
