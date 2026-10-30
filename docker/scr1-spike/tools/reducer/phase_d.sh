#!/usr/bin/env bash
# Шаг 5 / Фаза D (финал): LMA=VMA relink + пропуск crt reloc/bss, минимальное
# ядро, verbose-эпилог, контрастная пара larger/smaller, метрики.
# Запускается ВНУТРИ контейнера через run_container.sh.
set -euo pipefail
: "${SCR1_DIR:?}"
: "${WT:?}"
cd "$WT/docker/scr1-spike/tools/reducer"
exec python3 phase_d.py "$@"
