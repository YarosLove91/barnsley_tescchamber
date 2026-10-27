import re

COMMIT_RE = re.compile(r"core\s+\d+:\s+(\d+)\s+0x([0-9a-f]+)\s+\(0x([0-9a-f]+)\)(.*)")
GPR_RE = re.compile(r"\bx\s*(\d+)\s+0x([0-9a-f]+)")
CSR_RE = re.compile(r"\bc(\d+)_(\w+)\s+0x([0-9a-f]+)")
MEM_RE = re.compile(r"\bmem 0x([0-9a-f]+)(?:\s+0x([0-9a-f]+))?")

CSR_PRIORITY = (0x300, 0x305, 0x341, 0x342, 0x340, 0x304, 0x344,
                0xB00, 0xB80, 0xB02, 0xB82)


def mem_width(enc, is_store):
    if enc & 3 == 3:
        op = enc & 0x7F
        f3 = (enc >> 12) & 7
        if op == 0x23:
            return {0: 1, 1: 2, 2: 4}.get(f3, 4)
        if op == 0x03:
            return {0: 1, 1: 2, 2: 4, 4: 1, 5: 2}.get(f3, 4)
        return 4
    return 4


class Trace:
    def __init__(self, path, progress=False):
        self.pcs = []
        self.encs = []
        self.xw = []
        self.cw = []
        self.mem = []
        n = 0
        with open(path, "r", errors="replace") as f:
            for line in f:
                m = COMMIT_RE.match(line)
                if not m:
                    continue
                pc = int(m.group(2), 16)
                if pc == 0xF8:
                    break
                enc = int(m.group(3), 16)
                rest = m.group(4)
                self.pcs.append(pc)
                self.encs.append(enc)
                xw = [(int(a), int(b, 16)) for a, b in GPR_RE.findall(rest)]
                cw = [(int(a), int(b, 16)) for a, b, _ in
                      ((mm.group(1), mm.group(3), mm.group(2)) for mm in CSR_RE.finditer(rest))]
                mem = []
                for mm in MEM_RE.finditer(rest):
                    addr = int(mm.group(1), 16)
                    val = mm.group(2)
                    is_store = val is not None
                    mem.append((addr, int(val, 16) if is_store else None,
                                mem_width(enc, is_store), is_store))
                self.xw.append(xw)
                self.cw.append(cw)
                self.mem.append(mem)
                n += 1
        self.n = n

    def pc(self, i):
        return self.pcs[i]

    def gpr_state(self, p):
        st = {}
        for i in range(p + 1):
            for reg, val in self.xw[i]:
                st[reg] = val
        return st

    def csr_state(self, p):
        st = {}
        for i in range(p + 1):
            for num, val in self.cw[i]:
                st[num] = val
        return st

    def csr_state_filtered(self, p, cap=16):
        st = self.csr_state(p)
        order = sorted(st.keys(), key=lambda c: (CSR_PRIORITY.index(c) if c in CSR_PRIORITY
                                                 else len(CSR_PRIORITY), c))
        return [(c, st[c]) for c in order[:cap]]

    def stores_bytes_upto(self, p, skip_regions=()):
        out = {}
        for i in range(p + 1):
            for addr, val, width, is_store in self.mem[i]:
                if not is_store:
                    continue
                if any(lo <= addr < hi for lo, hi in skip_regions):
                    continue
                for b in range(width):
                    out[addr + b] = (val >> (8 * b)) & 0xFF
        return out

    def window_readset(self, p, c_end, skip_regions=()):
        stores = self.stores_bytes_upto(p, skip_regions)
        written = set()
        restore = {}
        for i in range(p + 1, c_end + 1):
            for addr, val, width, is_store in self.mem[i]:
                if any(lo <= addr < hi for lo, hi in skip_regions):
                    continue
                if is_store:
                    for b in range(width):
                        written.add(addr + b)
                else:
                    for b in range(width):
                        a = addr + b
                        if a not in written and a in stores and a not in restore:
                            restore[a] = stores[a]
        return restore
