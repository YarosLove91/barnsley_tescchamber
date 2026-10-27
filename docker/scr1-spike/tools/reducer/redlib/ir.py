import bisect
import re

from . import binutils

INSN_RE = re.compile(r"^\s+([0-9a-f]+):\s+([0-9a-f]{4}|[0-9a-f]{8})\s+(.*\S)\s*$")
FUNC_RE = re.compile(r"^([0-9a-f]+) <(.+)>:$")


class Instr:
    __slots__ = ("idx", "addr", "size", "enc", "text", "func", "section")

    def __init__(self, idx, addr, size, enc, text, func, section):
        self.idx = idx
        self.addr = addr
        self.size = size
        self.enc = enc
        self.text = text
        self.func = func
        self.section = section

    def enc_bytes(self):
        return self.enc.to_bytes(self.size, "little")

    def __repr__(self):
        return "Instr(%d, %#x, %d, %#0*x, %r)" % (
            self.idx, self.addr, self.size, self.size * 2, self.enc, self.text)


class IR:
    def __init__(self, env, elf):
        self.env = env
        self.elf = elf
        self.sections = [s for s in binutils.sections(env, elf) if s["alloc"]]
        self.sec_by_name = {s["name"]: s for s in self.sections}
        self.symbols = binutils.symbols(env, elf)
        self.entry = binutils.entry(env, elf)
        self.instrs = self._parse_disasm()
        self.addrs = [i.addr for i in self.instrs]

    def _parse_disasm(self):
        code_secs = [s for s in self.sections if s["code"] and s["contents"]]
        code_secs.sort(key=lambda s: s["vma"])
        text = binutils.disasm(self.env, self.elf)
        instrs = []
        func = None
        for line in text.splitlines():
            fm = FUNC_RE.match(line)
            if fm:
                func = fm.group(2)
                continue
            m = INSN_RE.match(line)
            if not m:
                continue
            addr = int(m.group(1), 16)
            tok = m.group(2)
            sec = next((s["name"] for s in code_secs
                        if s["vma"] <= addr < s["vma"] + s["size"]), None)
            if sec is None:
                continue
            instrs.append(Instr(len(instrs) + 1, addr, len(tok) // 2,
                                int(tok, 16), m.group(3), func, sec))
        return instrs

    def index_of(self, addr):
        i = bisect.bisect_left(self.addrs, addr)
        if i < len(self.instrs) and self.instrs[i].addr == addr:
            return i
        return None

    def trigger_range(self):
        start = self.symbols.get("ml_trigger_start")
        end = self.symbols.get("ml_trigger_end")
        if start is None or end is None:
            raise RuntimeError("trigger labels ml_trigger_start/end not in symbol table")
        return start, end

    def service_points(self):
        return {
            "entry": self.entry,
            "SIM_EXIT": self.symbols.get("SIM_EXIT", 0xF4),
            "SIM_STOP": self.symbols.get("SIM_STOP", 0xF8),
            "trap_vector": self.symbols.get("machine_trap_entry", 0x1C0),
            "trigger_start": self.symbols.get("ml_trigger_start"),
            "trigger_end": self.symbols.get("ml_trigger_end"),
        }

    def summary(self):
        ts, te = self.trigger_range()
        ti = self.index_of(ts)
        return {
            "static_total": len(self.instrs),
            "trigger_start": ts,
            "trigger_end": te,
            "trigger_static_idx": (ti + 1) if ti is not None else None,
            "entry": self.entry,
            "sections": {s["name"]: {"vma": s["vma"], "lma": s["lma"], "size": s["size"]}
                         for s in self.sections},
        }
