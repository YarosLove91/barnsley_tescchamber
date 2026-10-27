import re

from .env import sh

SEC_RE = re.compile(
    r"^\s*(\d+)\s+(\S+)\s+([0-9a-f]+)\s+([0-9a-f]+)\s+([0-9a-f]+)\s+([0-9a-f]+)\s+2\*\*(\d+)\s*(.*)$")


def sections(env, elf):
    out = sh([env.tool("objdump"), "-h", "-w", elf]).stdout
    secs = []
    for line in out.splitlines():
        m = SEC_RE.match(line)
        if not m:
            continue
        flags = m.group(8)
        secs.append(dict(
            idx=int(m.group(1)), name=m.group(2), size=int(m.group(3), 16),
            vma=int(m.group(4), 16), lma=int(m.group(5), 16),
            off=int(m.group(6), 16), align=int(m.group(7)),
            contents="CONTENTS" in flags, alloc="ALLOC" in flags,
            code="CODE" in flags, readonly="READONLY" in flags))
    return secs


def section_bytes(env, elf, sec):
    if not sec["contents"] or sec["size"] == 0:
        return b""
    with open(elf, "rb") as f:
        f.seek(sec["off"])
        return f.read(sec["size"])


def entry(env, elf):
    out = sh([env.tool("readelf"), "-h", "-W", elf]).stdout
    m = re.search(r"Entry point address:\s+0x([0-9a-f]+)", out)
    if not m:
        raise RuntimeError("no entry point in %s" % elf)
    return int(m.group(1), 16)


def symbols(env, elf):
    out = sh([env.tool("nm"), elf]).stdout
    syms = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 3 and re.fullmatch(r"[0-9a-f]{8,16}", parts[0]) and parts[1] in "TtDdBbRrWwAaGgVvNn":
            syms.setdefault(parts[2], int(parts[0], 16))
    return syms


def disasm(env, elf, wide=True):
    args = [env.tool("objdump"), "-d"]
    if wide:
        args.append("-w")
    args.append(elf)
    return sh(args).stdout


def full_dump(env, elf, out_path):
    txt = sh([env.tool("objdump"), "-D", "-w", "-x", "-S", elf]).stdout
    with open(out_path, "w") as f:
        f.write(txt)
    return out_path


def to_verilog_hex(env, elf, hex_path):
    sh([env.tool("objcopy"), "-O", "verilog", elf, hex_path])
    return hex_path
