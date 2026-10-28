#!/usr/bin/env bash
# Шаг 3 / Фаза B: pillar-бинпоиск головы + context setter.
# Запускается ВНУТРИ контейнера через run_container.sh.
set -euo pipefail
: "${SCR1_DIR:?}"
: "${WT:?}"
cd "$WT/docker/scr1-spike/tools/reducer"
exec python3 phase_b.py "$@"
