#!/usr/bin/env bash
# run_container.sh — запуск контейнера scr1-spike-verif по паттерну ТЗ §1:
# дерево монтируется ПО ТОМУ ЖЕ абсолютному пути, что и на хосте (иначе
# build-каталоги Verilator с абсолютными путями в .mk ломаются).
#
# Использование: run_container.sh <script.sh> [доп. аргументы docker run...]
#   WT — корень worktree (по умолчанию — репозиторий, содержащий этот скрипт).
set -euo pipefail

SCRIPT="${1:?usage: run_container.sh <script.sh>}"
WT="${WT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)}"
OUT="${OUT:-$WT/docker/scr1-spike/logs/reducer}"
mkdir -p "$OUT"

exec docker run --rm \
    -e SCR1_DIR="$WT/scr1" \
    -e REDUCER_OUT="$OUT" \
    -e WT="$WT" \
    -v "$WT:$WT" \
    -v "$OUT:/out" \
    -w "$WT" \
    scr1-spike-verif:latest bash "$SCRIPT"
