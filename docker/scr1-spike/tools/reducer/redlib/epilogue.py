from . import encode as E

OUTPORT = 0xF0000000
OUTPORT_HI = 0xF0000
SIM_EXIT = 0xF4
MARKER = ord("R")


def cut_stub(ep_addr):
    return E.words_to_bytes(list(E.jump_imm(E.T0, ep_addr)))


def trampoline_bytes(ep_addr):
    return E.words_to_bytes(list(E.jump_imm(E.T0, ep_addr)))


def stub_jal(from_addr, to_addr):
    return E.words_to_bytes([E.jal(E.X0, to_addr - from_addr)])


def gen_epilogue_min():
    words = [
        E.lui(E.T1, OUTPORT_HI),
        E.li_small(E.T2, MARKER),
        E.sb(E.T2, 0, E.T1),
        E.csrr(E.A1, E.CSR_MCYCLEH),
        E.snez(E.A0, E.A1),
        E.li_small(E.T0, SIM_EXIT),
        E.jr(E.T0),
    ]
    return E.words_to_bytes(words)


def gen_epilogue_direct():
    words = [
        E.lui(E.T1, OUTPORT_HI),
        E.li_small(E.T2, MARKER),
        E.sb(E.T2, 0, E.T1),
        E.csrr(E.A0, E.CSR_MCYCLEH),
        E.li_small(E.T0, SIM_EXIT),
        E.jr(E.T0),
    ]
    return E.words_to_bytes(words)


def gen_epilogue_verbose(str_addr, con_puts_addr, con_puthex_addr):
    words = []
    words += [E.lui(E.T1, OUTPORT_HI), E.li_small(E.T2, MARKER), E.sb(E.T2, 0, E.T1)]
    words += [E.csrr(E.S3, E.CSR_MCYCLEH)]
    hi, lo = E.split_hi_lo(str_addr)
    words += [E.lui(E.A0, hi), E.addi(E.A0, E.A0, lo)]
    words += list(E.call(E.T0, con_puts_addr))
    words += [E.lui(E.T1, OUTPORT_HI)]
    words += [E.addi(E.A0, E.S3, 0)]
    words += list(E.call(E.T0, con_puthex_addr))
    words += [E.lui(E.T1, OUTPORT_HI), E.li_small(E.T2, 10), E.sb(E.T2, 0, E.T1)]
    words += [E.snez(E.A0, E.S3), E.li_small(E.T0, SIM_EXIT), E.jr(E.T0)]
    return E.words_to_bytes(words)


def find_string_vma(ir, sec_name, needle):
    from . import binutils
    sec = ir.sec_by_name[sec_name]
    data = binutils.section_bytes(ir.env, ir.elf, sec)
    off = data.find(needle.encode() if isinstance(needle, str) else needle)
    if off < 0:
        raise KeyError("string %r not found in %s" % (needle, sec_name))
    return sec["vma"] + off
