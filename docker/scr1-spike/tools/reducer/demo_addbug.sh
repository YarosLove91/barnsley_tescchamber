#!/usr/bin/env bash
# Демо: редуктор на синтетическом аппаратном баге «сломанный add»
# (DEMO-ADDBUG в scr1_pipe_ialu.sv, локально, не коммитится).
# Запускается ВНУТРИ контейнера через run_container.sh.
set -euo pipefail
: "${SCR1_DIR:?}"
: "${WT:?}"
cd "$WT/docker/scr1-spike/tools/reducer"
exec python3 demo_addbug.py "$@"
