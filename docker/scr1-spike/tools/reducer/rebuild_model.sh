#!/usr/bin/env bash
# Пересборка Verilator-модели (после инъекции/отката DEMO-ADDBUG) + sanity-прогон.
# Использование: rebuild_model.sh [TARGET]   (по умолчанию issue80_core)
set -euo pipefail
: "${SCR1_DIR:?}"
OUT="${REDUCER_OUT:-/out}"
TARGET="${1:-issue80_core}"
cd "$SCR1_DIR"
T0=$SECONDS
make run_verilator CFG=MAX BUS=AHB TARGETS="$TARGET" > "$OUT/rebuild_model.log" 2>&1 || true
echo "wall_seconds=$((SECONDS-T0))"
BLD=$(ls -d build/verilator_AHB_MAX_imc_*_STATE_0 | grep -v host-bak | head -1)
cat "$BLD/test_results.txt"
sed -n "/issue80_core: minimal/,/rc = /p" "$OUT/rebuild_model.log" | head -8
echo REBUILD_DONE
