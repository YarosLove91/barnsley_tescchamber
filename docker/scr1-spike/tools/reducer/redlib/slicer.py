import os
import re

from . import binutils
from .env import sh

RAM_RANGE = (0x0, 0x10000)
TCM_RANGE = (0x480000, 0x490000)


def _region(addr):
    if RAM_RANGE[0] <= addr < RAM_RANGE[1]:
        return "RAM"
    if TCM_RANGE[0] <= addr < TCM_RANGE[1]:
        return "TCM"
    raise ValueError("address %#x outside RAM/TCM" % addr)


class SliceBuild:
    def __init__(self, env, base_elf):
        self.env = env
        self.base_elf = base_elf
        self.entry = binutils.entry(env, base_elf)
        secs = [s for s in binutils.sections(env, base_elf) if s["alloc"]]
        self.sections = []
        for s in secs:
            if s["size"] == 0 and re.match(r"\.?t?bss$|\.tdata", s["name"]):
                continue
            data = bytearray(binutils.section_bytes(env, base_elf, s)) if s["contents"] else None
            self.sections.append(dict(s, data=data))
        self.extras = []

    def find_section(self, addr):
        for s in self.sections:
            if s["data"] is not None and s["vma"] <= addr < s["vma"] + s["size"]:
                return s
        raise KeyError("no contents section at %#x" % addr)

    def patch(self, addr, data):
        s = self.find_section(addr)
        off = addr - s["vma"]
        if off + len(data) > s["size"]:
            raise ValueError("patch at %#x overflows section %s" % (addr, s["name"]))
        s["data"][off:off + len(data)] = data

    def add_extra(self, name, addr, data):
        self.extras.append(dict(name=name, addr=addr, data=bytes(data)))

    def build(self, outdir, name):
        os.makedirs(outdir, exist_ok=True)
        stem = os.path.join(outdir, name)
        s_lines = [".globl _start", ".set _start, %#x" % self.entry, ""]
        ld_lines = [
            'OUTPUT_ARCH("riscv")',
            "ENTRY(_start)",
            "MEMORY {",
            "  RAM (rwx) : ORIGIN = 0x0, LENGTH = 64K",
            "  TCM (rwx) : ORIGIN = 0x480000, LENGTH = 64K",
            "}",
            "SECTIONS {",
        ]
        emitted = set()
        for s in self.sections + self.extras:
            sname = s["name"]
            if sname in emitted:
                raise ValueError("duplicate section %s" % sname)
            emitted.add(sname)
            region = _region(s["vma"] if s in self.sections else s["addr"])
            if s in self.extras:
                addr, data, nobits = s["addr"], s["data"], False
                region = _region(addr)
            else:
                addr, data = s["vma"], s["data"]
                nobits = not s["contents"]
            aflags = ("ax" if s.get("code") else ("aw" if not s.get("readonly") else "a")) \
                if s in self.sections else "ax"
            if nobits:
                s_lines.append('.section %s,"aw",@nobits' % sname)
                if s["size"]:
                    s_lines.append(".space %d" % s["size"])
            else:
                binp = stem + "." + sname.lstrip(".") + ".bin"
                with open(binp, "wb") as f:
                    f.write(bytes(data))
                s_lines.append('.section %s,"%s",@progbits' % (sname, aflags))
                s_lines.append('.incbin "%s"' % binp)
            s_lines.append("")
            place = ">TCM" if region == "TCM" else ">RAM"
            if nobits:
                ld_lines.append("  %s %#x (NOLOAD) : { *(%s) } %s" % (sname, addr, sname, place))
            elif region == "TCM":
                ld_lines.append("  %s %#x : { *(%s) } >TCM AT>RAM" % (sname, addr, sname))
            else:
                ld_lines.append("  %s %#x : { *(%s) } >RAM" % (sname, addr, sname))
        ld_lines.append("}")
        s_path = stem + ".S"
        ld_path = stem + ".ld"
        with open(s_path, "w") as f:
            f.write("\n".join(s_lines) + "\n")
        with open(ld_path, "w") as f:
            f.write("\n".join(ld_lines) + "\n")
        elf = stem + ".elf"
        sh([self.env.tool("gcc"), "-nostartfiles", "-nostdlib",
            "-march=rv32imc_zicsr_zifencei", "-mabi=ilp32",
            "--specs=nano.specs", "-T", ld_path, s_path, "-o", elf])
        hexp = binutils.to_verilog_hex(self.env, elf, stem + ".hex")
        dump = binutils.full_dump(self.env, elf, stem + ".dump")
        return dict(elf=elf, hex=hexp, dump=dump, s=s_path, ld=ld_path)

    def base_hex(self, outdir):
        os.makedirs(outdir, exist_ok=True)
        return binutils.to_verilog_hex(self.env, self.base_elf,
                                       os.path.join(outdir, "base_ref.hex"))


def same_bytes(path_a, path_b):
    with open(path_a, "rb") as fa, open(path_b, "rb") as fb:
        return fa.read() == fb.read()
