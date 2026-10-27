import re
import subprocess
import time

COMMIT_RE = re.compile(r"core\s+\d+:\s+(\d+)\s+0x([0-9a-f]+)\s+\(0x([0-9a-f]+)\)(.*)")
GPR_RE = re.compile(r"\bx\s*(\d+)\s+0x([0-9a-f]+)")
CSR_RE = re.compile(r"\bc(\d+)_(\w+)\s+0x([0-9a-f]+)")
MEM_RE = re.compile(r"\bmem 0x([0-9a-f]+)\s+0x([0-9a-f]+)")

OUTPORT = 0xF0000000
STOP_PC = 0xF8
CSR_MCYCLE = 2816
CSR_MCYCLEH = 2944

SPIKE_FLAGS = [
    "--no-dm", "--disable-dtb", "--pc=0x200",
    "--isa=rv32imc_zicsr_zifencei",
    "-m0x0:0x10000,0x480000:0x10000,0x490000:0x1000,0xf0000000:0x1000",
]


class SpikeResult:
    def __init__(self):
        self.ok = False
        self.timed_out = False
        self.reached_stop = False
        self.n_commits = 0
        self.last_pc = None
        self.a0 = None
        self.console = ""
        self.mcycleh_final = None
        self.mcycle_final = None
        self.trigger_executed = False
        self.first_trigger_commit = None
        self.wall = None
        self.error = None
        self.log_path = None

    def to_dict(self):
        return {k: v for k, v in self.__dict__.items()}


def run_spike(elf, trigger_range=None, timeout=300.0, log_path=None,
              max_commits=5_000_000, spike_bin="spike"):
    r = SpikeResult()
    cmd = [spike_bin] + SPIKE_FLAGS + ["-l", "--log-commits", elf]
    t0 = time.monotonic()
    chars = []
    log_f = open(log_path, "w") if log_path else None
    p = None
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in p.stdout:
            if log_f:
                log_f.write(line)
            m = COMMIT_RE.match(line)
            if m:
                pc = int(m.group(2), 16)
                if pc == STOP_PC:
                    r.reached_stop = True
                    break
                if r.n_commits >= max_commits:
                    r.timed_out = True
                    break
                r.n_commits += 1
                r.last_pc = pc
                rest = m.group(4)
                for mm in GPR_RE.finditer(rest):
                    if int(mm.group(1)) == 10:
                        r.a0 = int(mm.group(2), 16)
                for mm in CSR_RE.finditer(rest):
                    num = int(mm.group(1))
                    val = int(mm.group(3), 16)
                    if num == CSR_MCYCLEH:
                        r.mcycleh_final = val
                    elif num == CSR_MCYCLE:
                        r.mcycle_final = val
                for mm in MEM_RE.finditer(rest):
                    if int(mm.group(1), 16) == OUTPORT:
                        chars.append(chr(int(mm.group(2), 16) & 0xFF))
                if trigger_range is not None:
                    ts, te = trigger_range
                    if ts <= pc < te:
                        if not r.trigger_executed:
                            r.first_trigger_commit = r.n_commits
                        r.trigger_executed = True
            elif "exception" in line or "Segmentation" in line or "cannot" in line:
                r.error = (r.error or "") + line.strip() + "\n"
            if time.monotonic() - t0 > timeout:
                r.timed_out = True
                break
    finally:
        if p is not None:
            p.kill()
            p.wait()
        if log_f:
            log_f.close()
    r.wall = time.monotonic() - t0
    r.console = "".join(chars)
    r.ok = r.reached_stop
    r.log_path = log_path
    return r
