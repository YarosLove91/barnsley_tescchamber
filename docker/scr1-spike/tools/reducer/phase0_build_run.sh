#!/usr/bin/env bash
# Фаза 0, шаг 1: сборка Verilator-модели (контейнер, same-path mount) и полный
# прогон mcycle_rtos на RTL. Ожидание: __FAIL + "BUG #80 reproduced" (баг жив).
# Запускается ВНУТРИ контейнера через run_container.sh.
set -euo pipefail
: "${SCR1_DIR:?}"
OUT="${REDUCER_OUT:-/out}"
mkdir -p "$OUT"

cd "$SCR1_DIR"
echo "=== [1/2] make run_verilator CFG=MAX BUS=AHB TARGETS=mcycle_rtos ==="
T0=$SECONDS
make run_verilator CFG=MAX BUS=AHB TARGETS=mcycle_rtos \
    > "$OUT/phase0_rtl_build_run.log" 2>&1 || true
echo "wall_seconds=$((SECONDS-T0))" > "$OUT/phase0_rtl_build_time.txt"
grep -E "Summary|Test passed|Test failed|mcycle_rtos" "$OUT/phase0_rtl_build_run.log" | tail -5 || true

BLD=$(ls -d build/verilator_AHB_MAX_imc_*_STATE_0 2>/dev/null | grep -v host-bak | head -1)
echo "BLD=$BLD"
echo "=== [2/2] консоль RTL + test_results ==="
sed -n '/boot: mcycle_rtos/,$p' "$OUT/phase0_rtl_build_run.log" | head -30 | tee "$OUT/phase0_rtl_console.txt"
cp "$BLD/test_results.txt" "$OUT/phase0_test_results.txt" 2>/dev/null || true
cat "$OUT/phase0_test_results.txt" 2>/dev/null || true
ls "$BLD"/mcycle_rtos.elf "$BLD"/mcycle_rtos.hex 2>/dev/null
cat "$OUT/phase0_rtl_build_time.txt" || true
echo PHASE0_BUILD_DONE
