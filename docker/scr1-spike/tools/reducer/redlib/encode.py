X0, RA, SP, GP, TP, T0, T1, T2 = 0, 1, 2, 3, 4, 5, 6, 7
S0, S1 = 8, 9
A0, A1, A2, A3, A4, A5, A6, A7 = 10, 11, 12, 13, 14, 15, 16, 17
S3, S4 = 19, 20
T3 = 28

CSR_MCYCLE = 0xB00
CSR_MCYCLEH = 0xB80

NOP = 0x00000013
C_NOP = 0x0001


def _r(funct7, rs2, rs1, funct3, rd, opcode):
    return (funct7 << 25) | (rs2 << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | opcode


def _i(imm, rs1, funct3, rd, opcode):
    return ((imm & 0xFFF) << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | opcode


def _s(imm, rs2, rs1, funct3, opcode):
    imm &= 0xFFF
    return ((imm >> 5) << 25) | (rs2 << 20) | (rs1 << 15) | (funct3 << 12) | ((imm & 31) << 7) | opcode


def _u(rd, imm20, opcode):
    return ((imm20 & 0xFFFFF) << 12) | (rd << 7) | opcode


def split_hi_lo(addr):
    lo = addr & 0xFFF
    hi = (addr >> 12) & 0xFFFFF
    if lo & 0x800:
        hi = (hi + 1) & 0xFFFFF
        lo -= 0x1000
    return hi, lo


def lui(rd, imm20):
    return _u(rd, imm20, 0x37)


def addi(rd, rs1, imm):
    return _i(imm, rs1, 0, rd, 0x13)


def sltu(rd, rs1, rs2):
    return _r(0, rs2, rs1, 3, rd, 0x33)


def snez(rd, rs):
    return sltu(rd, X0, rs)


def jalr(rd, rs1, imm=0):
    return _i(imm, rs1, 0, rd, 0x67)


def jal(rd, imm):
    if not (-2**20 <= imm < 2**20):
        raise ValueError("jal offset %#x out of +/-1MB range" % imm)
    imm &= 0x1FFFFF
    return (((imm >> 20) & 1) << 31) | (((imm >> 1) & 0x3FF) << 21) | \
        (((imm >> 11) & 1) << 20) | (((imm >> 12) & 0xFF) << 12) | (rd << 7) | 0x6F


def j(imm):
    return jal(X0, imm)


def jr(rs1):
    return jalr(X0, rs1, 0)


def call(reg_t, addr):
    hi, lo = split_hi_lo(addr)
    return lui(reg_t, hi), jalr(RA, reg_t, lo)


def jump_imm(reg_t, addr):
    hi, lo = split_hi_lo(addr)
    return lui(reg_t, hi), jalr(X0, reg_t, lo)


def sb(rs2, imm, rs1):
    return _s(imm, rs2, rs1, 0, 0x23)


def csrrs(rd, csr, rs1):
    return _i(csr, rs1, 2, rd, 0x73)


def csrr(rd, csr):
    return csrrs(rd, csr, X0)


def csrrw(rd, csr, rs1):
    return _i(csr, rs1, 1, rd, 0x73)


def words_to_bytes(words):
    return b"".join(w.to_bytes(4, "little") for w in words)


def li_small(rd, imm):
    return addi(rd, X0, imm)
