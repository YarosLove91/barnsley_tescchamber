#!/usr/bin/env bash
# Шаг 2 / Фаза A: хвостовой бинпоиск последней существенной инструкции.
# Запускается ВНУТРИ контейнера через run_container.sh.
set -euo pipefail
: "${SCR1_DIR:?}"
: "${WT:?}"
cd "$WT/docker/scr1-spike/tools/reducer"
exec python3 phase_a.py "$@"
