#!/usr/bin/env python3
"""Сравнение финального архитектурного состояния fern:
SCR1 (Verilator, STATE_DUMP=1 -> /out/fern_state_scr1.txt)
vs свежий Spike (--log-commits на ТОМ ЖЕ fern.elf, стоп по PC=0xF8).

Запуск: внутри контейнера scr1-spike-verif, примонтировав директорию с
артефактами в /out (см. docker/scr1-spike/run.sh — barnsley монтируется в
/work, поэтому: `cp /work/docker/scr1-spike/compare_state.py /out/` или
`docker run -v <artifacts>:/out -v $PWD/docker/scr1-spike:/scripts ...
python /scripts/compare_state.py`). Ожидает в /out: fern.elf и
fern_state_scr1.txt; пишет туда же fern_spike_commits.log и
fern_state_compare.txt.

Spike запускается штатными CLI-флагами, без модификации его кода:
  --no-dm      — debug module не занимает [0x0,0x1000) (там .text.init)
  --disable-dtb — иначе на reset() добавится boot ROM на 0x1000 (DEFAULT_RSTVEC)
                 и пересечётся с RAM-областью 0x0:0x10000
  --pc=0x200   — старт с entry (reset vector SCR1)
  -m0x0:0x10000,0x480000:0x10000,0x490000:0x1000,0xf0000000:0x1000
               — RAM 64K (text.init + LMA-копии секций, link_tcm.ld >TCM AT>RAM;
                 spike грузит по p_paddr, crt_tcm.S сам перемещает код в TCM),
                 TCM 0x480000 (VMA), mtime TCSR 0x490000, SIM_PRINT 0xf0000000
"""
import re
import subprocess

OUT = "/out"

cmd = [
    "spike", "--no-dm", "--disable-dtb", "--pc=0x200",
    "--isa=rv32imc_zicsr_zifencei",
    "-m0x0:0x10000,0x480000:0x10000,0x490000:0x1000,0xf0000000:0x1000",
    "-l", "--log-commits",
    f"{OUT}/fern.elf",
]
print("RUN:", " ".join(cmd), flush=True)
p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

ABI = ["zero","ra","sp","gp","tp","t0","t1","t2","s0","s1","a0","a1","a2","a3",
       "a4","a5","a6","a7","s2","s3","s4","s5","s6","s7","s8","s9","s10","s11",
       "t3","t4","t5","t6"]

re_insn = re.compile(r"core\s+\d+:\s+(\d+)\s+0x([0-9a-f]+)\s+\(0x([0-9a-f]+)\)(.*)")
re_gpr = re.compile(r"\bx\s*(\d+)\s+0x([0-9a-f]+)")
re_csr = re.compile(r"\bc(\d+)_(\w+)\s+0x([0-9a-f]+)")

gpr, csr = {}, {}
n_commits, stopped, last_pc = 0, False, None
with open(f"{OUT}/fern_spike_commits.log", "w") as f:
    for line in p.stdout:
        f.write(line)
        m = re_insn.match(line)
        if m:
            n_commits += 1
            last_pc = int(m.group(2), 16)
            rest = m.group(4)
            for mm in re_gpr.finditer(rest):
                gpr[int(mm.group(1))] = int(mm.group(2), 16)
            for mm in re_csr.finditer(rest):
                csr[mm.group(2)] = int(mm.group(3), 16)
            if last_pc == 0xF8:
                stopped = True
                break
p.kill()
p.wait()
print(f"spike commits: {n_commits}, reached PC=0xF8: {stopped}, last_pc={last_pc:#x}")
if not stopped:
    print("WARN: 0xF8 не достигнут — сравнение GPR может быть неполным")

# --- SCR1 state dump ---
scr1_gpr, scr1_csr, scr1_pc = {}, {}, None
text = open(f"{OUT}/fern_state_scr1.txt").read()
m = re.search(r"# pc:\s*0x([0-9a-f]+)", text)
if m:
    scr1_pc = int(m.group(1), 16)
for name, val in re.findall(r"(\w+):\s*0x([0-9a-f]{8})", text):
    if name in ABI:
        scr1_gpr[name] = int(val, 16)
for name, val in re.findall(
        r"^(mstatus|misa|mie|mtvec|mscratch|mepc|mcause|mtval|mip|mhartid|mcycle|mcycleh|minstret|minstreth)\s+0x([0-9a-f]+)",
        text, re.M):
    scr1_csr[name] = int(val, 16)

# --- GPR diff ---
print()
print(f"{'reg':>5} {'idx':>3} {'SCR1@0xF8':>12} {'Spike@0xF8':>12}  res")
mism = []
for i, name in enumerate(ABI):
    a = 0 if i == 0 else scr1_gpr.get(name)
    b = 0 if i == 0 else gpr.get(i)
    ok = (a == b)
    if not ok:
        mism.append(name)
    fa = f"{a:#010x}" if a is not None else "?"
    fb = f"{b:#010x}" if b is not None else "?"
    print(f"{name:>5} x{i:<2d} {fa:>12} {fb:>12}  {'OK' if ok else 'DIFF'}")
print()
print("PC:      SCR1", f"{scr1_pc:#010x}" if scr1_pc is not None else "?",
      " Spike", f"{last_pc:#010x}" if last_pc is not None else "?")
print("GPR mismatches:", mism if mism else "NONE — регистровый файл совпадает побитово")

# --- CSR side-by-side (счётчики не сравнимы по природе) ---
TIMING = {"mcycle", "mcycleh", "minstret", "minstreth", "time", "timeh"}
print()
print(f"{'CSR':>10} {'SCR1':>12} {'Spike':>12}  note")
for k in ["mstatus","misa","mie","mtvec","mscratch","mepc","mcause","mtval","mip","mhartid","mcycle","minstret"]:
    a, b = scr1_csr.get(k), csr.get(k)
    fa = f"{a:#010x}" if a is not None else "-"
    fb = f"{b:#010x}" if b is not None else "-"
    note = "timing — не сравним" if k in TIMING else ("OK" if a == b else "DIFF")
    print(f"{k:>10} {fa:>12} {fb:>12}  {note}")

verdict = (not mism) and stopped and scr1_pc == 0xF8
print()
print("RESULT:", "GPR MATCH — SCR1 (RTL) == fresh Spike на идентичном бинаре fern.elf"
      if verdict else "ЕСТЬ РАСХОЖДЕНИЯ — см. выше")
with open(f"{OUT}/fern_state_compare.txt", "w") as f:
    f.write(f"commits={n_commits} stopped_at_F8={stopped}\n")
    for i, name in enumerate(ABI):
        f.write(f"{name} {scr1_gpr.get(name)} {gpr.get(i)}\n")
    f.write(f"verdict={'GPR_MATCH' if verdict else 'MISMATCH:'+','.join(mism)}\n")
