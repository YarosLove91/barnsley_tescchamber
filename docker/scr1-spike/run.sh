#!/usr/bin/env bash
# =============================================================================
# run.sh — запуск контейнера scr1-spike-verif с примонтированным workspace.
#
# Монтирование:
#   $HOST_DIR (по умолчанию корень репо barnsley, внутри него scr1/) -> /work
#   Код доступен и из хост-ОС, и из контейнера; артефакты сборки SCR1
#   (build/trace/*.vcd, *.log) остаются на хосте — можно смотреть wavepeek'ом.
#   Именованный том scr1-verif-home -> /home/divefuzz: oh-my-zsh/настройки/
#   история zsh/vscode-server переживают перезапуски (при первом запуске том
#   наполняется из образа). Сброс: docker volume rm scr1-verif-home
#
# Использование:
#   docker/scr1-spike/run.sh                     # zsh внутри контейнера
#   HOST_DIR=~/Work/barnsley/scr1 ./run.sh       # примонтировать только scr1
#   PORT=2223 ./run.sh                           # другой порт SSH
#   повторный запуск скрипта при живом контейнере = docker exec в него
#
# Внутри контейнера:
#   cd /work/scr1 && make run_verilator CFG=MAX BUS=AHB TARGETS=hello
# VS Code Remote-SSH:  ssh://divefuzz@localhost:2222  (пароль divefuzz)
#
# NB: uid divefuzz в образе = 1000; если uid хозяина совпадает, права на
# примонтированные файлы seamless.
# =============================================================================
set -euo pipefail

IMAGE="${IMAGE:-scr1-spike-verif:latest}"
NAME="${NAME:-scr1-verif}"
PORT="${PORT:-2222}"
HOST_DIR="${HOST_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"

[ -d "$HOST_DIR" ] || { echo "ERROR: HOST_DIR=$HOST_DIR не существует" >&2; exit 1; }
[ -d "$HOST_DIR/scr1" ] || echo "WARN: в $HOST_DIR нет scr1/ — монтируется как есть" >&2

docker image inspect "$IMAGE" >/dev/null 2>&1 || {
    echo "ERROR: образ $IMAGE не найден. Соберите:" >&2
    echo "  docker build --progress=plain -t $IMAGE $(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" >&2
    exit 1
}

# Контейнер уже запущен — просто заходим внутрь (без нового run).
if docker ps --format '{{.Names}}' | grep -qx "$NAME"; then
    exec docker exec -u divefuzz -it "$NAME" zsh
fi

docker volume create "$NAME-home" >/dev/null

exec docker run --rm -it \
    --name "$NAME" \
    -p "$PORT:22" \
    -v "$HOST_DIR:/work" \
    -v "$NAME-home:/home/divefuzz" \
    "$IMAGE"
