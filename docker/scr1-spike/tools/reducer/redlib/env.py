import os
import re
import glob
import subprocess
from pathlib import Path


class Env:
    def __init__(self, wt=None, scr1_dir=None, out=None, bld=None, cross="riscv64-unknown-elf-"):
        here = Path(__file__).resolve()
        default_wt = str(here.parents[5])
        self.wt = wt or os.environ.get("WT") or default_wt
        self.scr1_dir = scr1_dir or os.environ.get("SCR1_DIR") or os.path.join(self.wt, "scr1")
        self.out = out or os.environ.get("REDUCER_OUT") or os.path.join(
            self.wt, "docker", "scr1-spike", "logs", "reducer")
        self.tools = str(here.parents[1])
        self.cross = cross
        os.makedirs(self.out, exist_ok=True)
        self._bld = bld

    @property
    def bld(self):
        if self._bld is None:
            cands = [d for d in glob.glob(os.path.join(self.scr1_dir, "build", "verilator_*"))
                     if not d.endswith(".host-bak")
                     and os.path.exists(os.path.join(d, "verilator", "Vscr1_top_tb_ahb"))]
            if not cands:
                raise RuntimeError("no verilator build dir with Vscr1_top_tb_ahb under %s/build" % self.scr1_dir)
            self._bld = sorted(cands)[0]
        return self._bld

    @property
    def v_bin(self):
        return os.path.join(self.bld, "verilator", "Vscr1_top_tb_ahb")

    @property
    def base_elf(self):
        return os.path.join(self.bld, "mcycle_rtos.elf")

    def tool(self, name):
        return self.cross + name


def sh(cmd, cwd=None, timeout=None, check=True):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if check and p.returncode != 0:
        raise RuntimeError("cmd failed (%d): %s\n%s" % (p.returncode, " ".join(cmd), p.stderr[-4000:]))
    return p
