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
                           jump_imm, li_small, lui, sb, words_to_bytes,
                           CSR_MCYCLE, CSR_MCYCLEH)

CORE_ADDR = 0x3000
OUTPORT_HI = 0xF0000
MARKER = ord("R")
FAILING_ENC = 0xB0001073  # csrw mcycle,zero — оригинальные байты виновной инструкции


def find_reloc_skip(ir, de_addr):
    init = [i for i in ir.instrs if i.section == ".text.init"]
    beq = None
    for ins in init:
        if ins.addr > de_addr and (ins.enc & 0x7F) == 0x63:
            beq = ins
            break
    if beq is None:
        raise RuntimeError("reloc-skip branch not found after %#x" % de_addr)
    target = None
    for ins in init:
        if ins.addr > beq.addr and ins.enc == 0xA0018613:
            target = ins.addr
            break
    if target is None or target - beq.addr > 64:
        raise RuntimeError("bss-start addi a2,gp not found near %#x" % beq.addr)
    return beq.addr, target


def find_gp_init(ir):
    for ins in ir.instrs:
        if ins.section == ".text.init" and ins.addr >= 0x200 \
                and (ins.enc & 0x7F) == 0x17 and ((ins.enc >> 7) & 31) == 3:
            return ins.addr
    raise RuntimeError("gp init (auipc gp) not found")


def gen_core(with_digit=True, failing_nop=False):
    words = [
        li_small(T0, -256),            # t0 = 0xffffff00
        csrrw(X0, CSR_MCYCLE, T0),     # предусловие: mcycle[31:8] = 0xFFFFFF
        NOP if failing_nop else FAILING_ENC,   # csrw mcycle,zero — байты оригинала
        lui(T1, OUTPORT_HI),           # t1 = 0xF0000000 (outport)
        li_small(T2, MARKER),
        sb(T2, 0, T1),                 # маркер 'R'
        csrr(A0, CSR_MCYCLEH),         # a0 = mcycleh (0 spike / 1+ RTL)
    ]
    if with_digit:
        words += [addi(T2, A0, 48), sb(T2, 0, T1)]
    words += [li_small(T0, 0xF4), jr(T0)]
    return words_to_bytes(words)


def main():
    ap = argparse.ArgumentParser()
    args = ap.parse_args()

    env = Env()
    out = os.path.join(env.out, "phaseD")
    os.makedirs(out, exist_ok=True)
    ir = IR(env, env.base_elf)

    with open(os.path.join(env.out, "phaseA", "phaseA_report.json")) as f:
        pa = json.load(f)
    fail_pc = int(pa["result"]["failing_pc"], 16)
    fail_ins = ir.instrs[ir.index_of(fail_pc)]
    assert fail_ins.enc == FAILING_ENC, "failing enc mismatch: %#x" % fail_ins.enc

    bss_end_addr, bss_rd = find_data_end_pair(ir, ir.symbols["__BSS_END__"])
    bss_start = ir.symbols.get("__BSS_START__", ir.sec_by_name[".sbss"]["vma"])
    cm_addr = find_call_main_pair(ir, ir.symbols["main"])
    de_addr, _ = find_data_end_pair(ir, ir.symbols["__DATA_END__"])
    beq_addr, skip_target = find_reloc_skip(ir, de_addr)
    gp_addr = find_gp_init(ir)
    print("crt patches: reloc-skip %#x->%#x, bss-end %#x->%#x, call-main %#x->CORE %#x"
          % (beq_addr, skip_target, bss_end_addr, bss_start, cm_addr, CORE_ADDR))

    sig = Signature80((CORE_ADDR, CORE_ADDR + 64))
    oracle = Oracle(env, sig)
    report = {"core_addr": hex(CORE_ADDR), "failing_enc": "%08x" % FAILING_ENC,
              "crt_patches": {"reloc_skip": [hex(beq_addr), hex(skip_target)],
                              "bss_end": hex(bss_end_addr), "call_main": hex(cm_addr),
                              "zero_regs_skip": [hex(0x200), hex(gp_addr)]},
              "variants": {}, "rtl_runs": 0}
    t_start = time.monotonic()

    def build_core(name, with_digit=True, failing_nop=False, skip_zero=False):
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
             "spike_wall": round(res.spike.wall, 3) if res.spike else None,
             "rtl_wall": round(res.rtl.wall, 3) if res.rtl else None,
             "elf": art["elf"], "hex": art["hex"], "dump": art["dump"]}
        if res.spike is not None:
            v["spike_console"] = res.spike.console
        if res.rtl is not None:
            v["rtl_console"] = res.rtl.console.strip()[-200:]
        report["variants"][tag] = v
        print("%-12s: %s (commits=%s a0=%s spike %.2fs rtl %.2fs)%s" % (
            tag, res.status, v["spike_commits"], v["spike_a0"],
            v["spike_wall"] or -1, v["rtl_wall"] or -1,
            " [cached]" if res.cached else ""))
        return res

    art, w = build_core("cutD_min")
    r_min = probe(art, "D_min", w)
    if r_min.status != "SameBug":
        print("FATAL: D_min is %s" % r_min.status)
        report["fatal"] = "D_min %s" % r_min.status
        _dump(out, report)
        return 2

    art, w = build_core("cutD_nozero", skip_zero=True)
    r_nz = probe(art, "D_nozero", w)

    art, w = build_core("cutD_verbose", with_digit=True,
                        skip_zero=(r_nz.status == "SameBug"))
    r_v = probe(art, "D_verbose", w)

    art, w = build_core("cutD_smaller", with_digit=True, failing_nop=True,
                        skip_zero=(r_nz.status == "SameBug"))
    r_s = probe(art, "D_smaller", w)

    best = r_nz.status == "SameBug"
    n_commits = (report["variants"]["D_verbose"]["spike_commits"]
                 or report["variants"]["D_nozero"]["spike_commits"])
    report["metrics"] = {
        "baseline_commits": 336694,
        "baseline_static_instrs": 3370,
        "final_commits": n_commits,
        "dynamic_reduction_pct": round(100.0 * (1 - n_commits / 336694), 5) if n_commits else None,
        "core_words": report["variants"]["D_verbose"]["core_words"],
        "zero_regs_skipped": best,
        "contrast_pair": {
            "larger": "cutD_verbose (SameBug, виновная csrw на месте)",
            "smaller": "cutD_smaller (виновная csrw → NOP)",
            "smaller_status": r_s.status,
            "diff": "единственная инструкция csrw mcycle,zero (b0001073)",
        },
    }
    report["wall_seconds"] = round(time.monotonic() - t_start, 1)
    ok = (r_min.status == "SameBug" and r_v.status == "SameBug"
          and r_s.status == "NoBug")
    report["phaseD_accepted"] = ok

    print()
    print("final core: %d words @%#x, динамика %s коммитов (−%s %%), zero_regs_skip=%s" % (
        report["variants"]["D_verbose"]["core_words"], CORE_ADDR, n_commits,
        report["metrics"]["dynamic_reduction_pct"], best))
    print("contrast: larger=SameBug smaller=%s (diff = виновная csrw)" % r_s.status)
    print("PHASE_D:", "OK" if ok else "FAIL")
    _dump(out, report)
    return 0 if ok else 1


def _dump(out, report):
    path = os.path.join(out, "phaseD_report.json")
    with open(path, "w") as f:
        json.dump(report, f, indent=1)
    print("report:", path)


if __name__ == "__main__":
    sys.exit(main())
