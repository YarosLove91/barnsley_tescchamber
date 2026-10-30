#!/usr/bin/env bash
# Фаза E (расширение): minstret-контрпример — симметричный баг #80
# (scr1_pipe_csr.sv:945-946), ядро в RAM 0x3000 по механике фазы D.
# Запускается ВНУТРИ контейнера через run_container.sh.
set -euo pipefail
: "${SCR1_DIR:?}"
: "${WT:?}"
cd "$WT/docker/scr1-spike/tools/reducer"
exec python3 phase_e.py "$@"
