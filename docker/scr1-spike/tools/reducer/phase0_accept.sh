#!/usr/bin/env bash
# Фаза 0, приёмка: ground truth (IR), identity-срез (hex байт-в-байт),
# оракул SameBug x N прогонов на полном mcycle_rtos, тайминги ISS/RTL.
# Запускается ВНУТРИ контейнера через run_container.sh.
set -euo pipefail
: "${SCR1_DIR:?}"
: "${WT:?}"
cd "$WT/docker/scr1-spike/tools/reducer"
exec python3 phase0_accept.py "$@"
