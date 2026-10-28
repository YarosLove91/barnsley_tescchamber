from . import encode as E
from .encode import (X0, RA, T0, T1, T2, addi, csrrw, jal, lui, sb, split_hi_lo, sw,
                     words_to_bytes)

SCR1_CSR_WHITELIST = frozenset((
    0x300,  # mstatus
    0x304,  # mie
    0x305,  # mtvec
    0x340,  # mscratch
    0x341,  # mepc
    0x342,  # mcause
    0x344,  # mip
    0xB00,  # mcycle
    0xB02,  # minstret
    0xB80,  # mcycleh
    0xB82,  # minstreth
))


def filter_csrs(items):
    """Spike логирует АППАРАТНЫЕ записи CSR (mret/trap), включая mstatush(0x310),
    которого НЕТ в SCR1 — csrw такого CSR на RTL = illegal instruction → trap → hang.
    Восстанавливать можно только CSR, реализуемые SCR1 (whitelist)."""
    return [(num, val) for num, val in items if num in SCR1_CSR_WHITELIST]


def materialize(rd, val):
    val &= 0xFFFFFFFF
    sv = val - 0x100000000 if val >= 0x80000000 else val
    if -2048 <= sv <= 2047:
        return [addi(rd, X0, sv & 0xFFF)]
    hi, lo = split_hi_lo(val)
    words = [lui(rd, hi)]
    if lo:
        words.append(addi(rd, rd, lo & 0xFFF))
    return words


def materialize_pair(rd, val):
    hi, lo = split_hi_lo(val & 0xFFFFFFFF)
    return [lui(rd, hi), addi(rd, rd, lo & 0xFFF)]


def _mem_words(restores):
    words = []
    if not restores:
        return words
    blocks = {}
    for a in sorted(restores):
        blocks.setdefault(a & ~0x7FF, []).append(a)
    for block in sorted(blocks):
        hi, lo = split_hi_lo(block)
        words.append(lui(T1, hi))
        if lo:
            words.append(addi(T1, T1, lo & 0xFFF))
        items = blocks[block]
        i = 0
        while i < len(items):
            a = items[i]
            if a % 4 == 0 and items[i:i + 4] == [a, a + 1, a + 2, a + 3]:
                val = (restores[a] | (restores[a + 1] << 8)
                       | (restores[a + 2] << 16) | (restores[a + 3] << 24))
                words += materialize(T2, val)
                words.append(sw(T2, a - block, T1))
                i += 4
            else:
                words.append(addi(T2, X0, restores[a]))
                words.append(sb(T2, a - block, T1))
                i += 1
    return words


def gen_setter(restores, gpr_vals, csr_items, window_pc, setter_vma):
    words = []
    words += _mem_words(restores)
    for r in range(1, 32):
        if r == T0:
            continue
        words += materialize(r, gpr_vals.get(r, 0))
    for num, val in csr_items:
        words += materialize(T0, val)
        words.append(csrrw(X0, num, T0))
    words += materialize(T0, gpr_vals.get(T0, 0))
    jal_addr = setter_vma + 4 * len(words)
    words.append(jal(X0, window_pc - jal_addr))
    return words_to_bytes(words)


def _auipc_val(addr, enc):
    return (addr + (enc & 0xFFFFF000)) & 0xFFFFFFFF


def _sext12(enc):
    imm = enc >> 20
    return imm - 0x1000 if imm & 0x800 else imm


def find_data_end_pair(ir, data_end_value):
    hits = []
    init = [i for i in ir.instrs if i.section == ".text.init"]
    for a, b in zip(init, init[1:]):
        if b.addr != a.addr + 4:
            continue
        if (a.enc & 0x7F) != 0x17 or (b.enc & 0x7F) != 0x13:
            continue
        rd_a = (a.enc >> 7) & 31
        rd_b = (b.enc >> 7) & 31
        rs_b = (b.enc >> 15) & 31
        if rd_a != rd_b or rs_b != rd_b:
            continue
        val = (_auipc_val(a.addr, a.enc) + _sext12(b.enc)) & 0xFFFFFFFF
        if val == data_end_value:
            hits.append((a.addr, rd_a))
    if len(hits) != 1:
        raise RuntimeError("expected 1 auipc+addi pair for %#x, got %s" % (data_end_value, hits))
    return hits[0]


def find_call_main_pair(ir, main_addr):
    hits = []
    init = [i for i in ir.instrs if i.section == ".text.init"]
    for a, b in zip(init, init[1:]):
        if b.addr != a.addr + 4:
            continue
        if (a.enc & 0x7F) != 0x17 or (b.enc & 0x7F) != 0x67:
            continue
        rd_a = (a.enc >> 7) & 31
        rd_b = (b.enc >> 7) & 31
        rs_b = (b.enc >> 15) & 31
        if rd_b != RA or rs_b != rd_a:
            continue
        val = ((_auipc_val(a.addr, a.enc) + _sext12(b.enc)) & 0xFFFFFFFF) & ~1
        if val == main_addr:
            hits.append(a.addr)
    if len(hits) != 1:
        raise RuntimeError("expected 1 call-main pair, got %s" % [hex(h) for h in hits])
    return hits[0]
