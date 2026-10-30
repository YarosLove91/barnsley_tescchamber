#!/usr/bin/env bash
# Верификация standalone-теста scr1/sim/tests/issue80_core:
#   RTL (Verilator, CFG=MAX BUS=AHB): a0=3, __FAIL, оба бага в консоли;
#   fresh Spike (тот же ELF): a0=0, «OK: high halves unchanged».
# Запускается ВНУТРИ контейнера через run_container.sh.
set -euo pipefail
: "${SCR1_DIR:?}"
: "${WT:?}"
OUT="${REDUCER_OUT:-/out}"

cd "$SCR1_DIR"
make run_verilator CFG=MAX BUS=AHB TARGETS=issue80_core \
    > "$OUT/issue80_core_build_run.log" 2>&1 || true
BLD=$(ls -d build/verilator_AHB_MAX_imc_*_STATE_0 | grep -v host-bak | head -1)

echo "=== test_results ==="
cat "$BLD/test_results.txt"
echo "=== RTL console ==="
sed -n '/issue80_core: minimal/,/rc = /p' "$OUT/issue80_core_build_run.log" | head -10

grep -q "issue80_core.hex.*__FAIL" "$BLD/test_results.txt" \
    || { echo "RTL: ожидался __FAIL"; exit 1; }
grep -aq "BUG #80 (mcycle)" "$OUT/issue80_core_build_run.log" \
    || { echo "RTL: нет строки mcycle-бага"; exit 1; }
grep -aq "BUG #80 (minstret)" "$OUT/issue80_core_build_run.log" \
    || { echo "RTL: нет строки minstret-бага"; exit 1; }
echo "RTL_OK: __FAIL, оба бага воспроизведены"

cd "$WT/docker/scr1-spike/tools/reducer"
python3 - <<'PY'
import os
import sys
sys.path.insert(0, '.')
from redlib.env import Env
from redlib.spike import run_spike
env = Env()
elf = os.path.join(env.bld, 'issue80_core.elf')
sp = run_spike(elf, timeout=120)
print('=== Spike ===')
print('reached_stop:', sp.reached_stop, 'commits:', sp.n_commits, 'a0:', sp.a0)
print(sp.console)
assert sp.reached_stop and sp.a0 == 0, 'spike side FAILED'
assert 'OK: high halves unchanged' in sp.console
print('SPIKE_OK: a0=0, high halves unchanged')
PY
echo "VERIFY_ISSUE80_CORE: OK"
