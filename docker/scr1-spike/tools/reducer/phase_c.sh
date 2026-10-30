#!/usr/bin/env bash
# Шаг 4 / Фаза C: ddmin середины (NOP-патчи сеттера и окна).
# Запускается ВНУТРИ контейнера через run_container.sh.
set -euo pipefail
: "${SCR1_DIR:?}"
: "${WT:?}"
cd "$WT/docker/scr1-spike/tools/reducer"
exec python3 phase_c.py "$@"
