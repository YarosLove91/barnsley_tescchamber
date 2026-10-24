#!/bin/sh
# entrypoint.sh — стартует sshd (для VS Code Remote-SSH), затем exec "$@" (CMD).
#
# sshd требует root (привилегированный порт 22 + privilege separation), а
# интерактивная консоль должна быть под обычным пользователем divefuzz:
# при запуске от root поднимаем sshd и сбрасываем привилегии через setpriv.
# `docker exec` НЕ проходит через entrypoint — для него:
#   docker exec -u divefuzz -it <container> zsh
set -e

mkdir -p /run/sshd

if [ "$(id -u)" = "0" ]; then
    ssh-keygen -A >/dev/null 2>&1 || true
    /usr/sbin/sshd || echo "entrypoint: warning: sshd failed to start" >&2
    exec setpriv --reuid=divefuzz --regid=divefuzz --init-groups \
        env HOME=/home/divefuzz USER=divefuzz LOGNAME=divefuzz SHELL=/usr/bin/zsh "$@"
else
    /usr/sbin/sshd 2>/dev/null \
        || echo "entrypoint: sshd not started (need root; run container with -u root)" >&2
    exec "$@"
fi
