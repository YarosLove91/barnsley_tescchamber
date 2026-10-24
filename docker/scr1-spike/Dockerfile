# syntax=docker/dockerfile:1.7
# =============================================================================
# scr1-spike-verif — верификация SCR1 против свежего Spike (PROMTS/PROMT_SPIKE.md)
# База — образ DiveFuzz (divefuzz:latest, Debian 13 trixie): python3.13 + venv
# (numpy/matplotlib/PyYAML/Cython...), riscv64-unknown-elf binutils/gcc (Debian),
# dtc/boost — всё это остаётся в образе и доступно для верификации.
#
# Добавлено поверх:
#   1. Spike — СВЕЖИЙ master на момент сборки. Коммит НЕ фиксируется, но
#      ОБЯЗАТЕЛЬНО логируется (лог сборки + /opt/riscv/share/spike-version.txt).
#      NB: master с 2026-10 требует clone --recursive (подмодуль
#      berkeley-softfloat-3: specialize_upstream.h), иначе сборка падает.
#   2. Verilator v5.052 из исходников (неизменяемый тег).
#      Fallback при lint-проблемах: --build-arg VERILATOR_REF=v5.006
#   3. SCR1 из https://github.com/YarosLove91/scr1.git (HTTPS, master) + submodules.
#   4. Toolchain xPack riscv-none-elf-gcc 15.2.0 (тот же, на котором на хосте
#      пройдено 224/224) — в /opt/xpack, плюс симлинки riscv64-unknown-elf-* в
#      /usr/local/bin: SCR1 Makefile/tb ждут именно этот префикс и nano.specs
#      (Debian-gcc без newlib, Ubuntu-gcc тоже — nano.specs нет ни там, ни там).
#   5. QEMU RISC-V (qemu-system-misc), make/g++/perl/git — в рантайме DiveFuzz
#      их нет, а для сборки Verilator-моделей SCR1 они нужны.
#   6. Консоль: zsh + oh-my-zsh (autosuggestions, syntax-highlighting) для
#      пользователя divefuzz; CMD = /bin/zsh.
#   7. Dev-инструменты: линковщик mold, SMT-решатель Z3 (+ z3-solver в python
#      venv), openssh-server + entrypoint.sh — для подключения VS Code
#      (Remote-SSH) внутрь контейнера.
#   8. riscv-pk (proxy kernel, из исходников, коммит логируется): `pk` (rv64) и
#      `pk32` (rv32imac) — запуск payload'ов как в README riscv-isa-sim:
#        spike -d pk hello          # rv64, с дизассемблером
#        spike --isa=rv32imac_zicsr_zifencei -d pk32 hello32
#
# Сборка:  docker build --progress=plain -t scr1-spike-verif:latest docker/scr1-spike \
#            2>&1 | tee docker/scr1-spike/logs/build.log
# Запуск:  docker run --rm -it scr1-spike-verif:latest            # zsh, без sshd-порта
#          docker run --rm -it -p 2222:22 scr1-spike-verif:latest # + SSH на :2222
# VS Code: Remote-SSH: Connect to Host... -> ssh://divefuzz@localhost:2222
#          (пароль divefuzz — смените!; детали — у слоя sshd ниже)
# =============================================================================

ARG BASE_IMAGE=divefuzz:latest

# =============================================================================
# Stage 1: Spike (самый свежий master, коммит логируется)
# =============================================================================
FROM ${BASE_IMAGE} AS spike-builder
USER root
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential git ca-certificates \
        autoconf automake libtool pkg-config gawk \
        device-tree-compiler libfdt-dev \
        libboost-regex-dev libboost-system-dev \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --recursive https://github.com/riscv-software-src/riscv-isa-sim.git /tmp/spike \
    && cd /tmp/spike \
    && echo "Spike commit: $(git rev-parse HEAD)" \
    && mkdir -p /opt/riscv/share \
    && printf 'spike_commit=%s\nspike_describe=%s\nspike_date=%s\n' \
          "$(git rev-parse HEAD)" \
          "$(git describe --always --tags 2>/dev/null || echo unknown)" \
          "$(git log -1 --format=%cI)" \
          > /opt/riscv/share/spike-version.txt \
    && mkdir build && cd build \
    && ../configure --prefix=/opt/riscv \
    && make -j"$(nproc)" \
    && make install

RUN test -x /opt/riscv/bin/spike \
    && /opt/riscv/bin/spike --help >/dev/null \
    && echo "Spike binary OK"

# =============================================================================
# Stage 2: Verilator 5.052 из исходников
# =============================================================================
FROM ${BASE_IMAGE} AS verilator-builder
USER root
ENV DEBIAN_FRONTEND=noninteractive

ARG VERILATOR_REF=v5.052

RUN apt-get update && apt-get install -y --no-install-recommends \
        git make autoconf g++ flex bison perl python3 \
        ca-certificates libfl2 libfl-dev zlib1g zlib1g-dev \
        libgoogle-perftools-dev numactl help2man \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 --branch "${VERILATOR_REF}" \
        https://github.com/verilator/verilator.git /tmp/verilator \
    && cd /tmp/verilator \
    && autoconf && ./configure --prefix=/opt/verilator \
    && make -j"$(nproc)" && make install

RUN /opt/verilator/bin/verilator --version

# =============================================================================
# Stage 3: riscv-pk — proxy kernel для Spike (`spike -d pk hello` из README
# riscv-isa-sim). Две сборки одним xPack-тулчейном:
#   pk   — rv64 (дефолт xpack gcc)
#   pk32 — rv32imac/ilp32 (для сравнения с RV32-прогонами SCR1 на Spike;
#          A-расширение включено, т.к. pk использует атомики в спинлоках —
#          запускать под `spike --isa=rv32imac_zicsr_zifencei pk32 ...`)
# =============================================================================
FROM ${BASE_IMAGE} AS pk-builder
USER root
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        git ca-certificates build-essential autoconf automake libtool \
    && rm -rf /var/lib/apt/lists/*

# Тот же xPack-тарболл, что и в runtime (слой закеширован — копия бесплатна).
COPY xpack-riscv-none-elf-gcc-*-linux-x64.tar.gz /tmp/xpack.tar.gz
RUN mkdir -p /opt/xpack-dist \
    && tar -xzf /tmp/xpack.tar.gz -C /opt/xpack-dist --strip-components=1 \
    && rm /tmp/xpack.tar.gz
ENV PATH="/opt/xpack-dist/bin:${PATH}"

# NB: configure riscv-pk ПЕРЕЗАПИСЫВАЕТ CFLAGS своими (configure.ac: CFLAGS="-Wall
# -Werror ..."), поэтому -march через CFLAGS не работает — только штатные
# --with-arch/--with-abi (Makefile.in подставит march/mabi сам). xPack GCC 15 по
# умолчанию собирает без _zicsr, а pk наполнен csrr/csrw → arch ОБЯЗАТЕЛЬНО с
# _zicsr_zifencei. --with-payload НЕ передаём: дефолт configure = dummy_payload
# (со значением none master падает: "No rule to make target 'none'").
RUN git clone https://github.com/riscv-software-src/riscv-pk.git /tmp/riscv-pk \
    && cd /tmp/riscv-pk \
    && echo "riscv-pk commit: $(git rev-parse HEAD)" \
    && mkdir build64 && cd build64 \
    && ../configure --prefix=/opt/riscv-pk --host=riscv-none-elf \
         --with-arch=rv64imac_zicsr_zifencei --with-abi=lp64 \
    && make -j"$(nproc)" && make install \
    && cd /tmp/riscv-pk && mkdir build32 && cd build32 \
    && ../configure --prefix=/opt/riscv-pk32 --host=riscv-none-elf \
         --with-arch=rv32imac_zicsr_zifencei --with-abi=ilp32 \
    && make -j"$(nproc)" && make install \
    && ls -l /opt/riscv-pk/riscv-none-elf/bin/pk /opt/riscv-pk32/riscv-none-elf/bin/pk

# =============================================================================
# Stage 4: runtime (база — DiveFuzz: python/venv/библиотеки сохраняются)
# =============================================================================
FROM ${BASE_IMAGE} AS runtime
USER root
ENV DEBIAN_FRONTEND=noninteractive

# Добираем то, чего нет в рантайме DiveFuzz: git/ca-certificates (клон SCR1),
# make/g++/perl (сборка Verilator-моделей SCR1), qemu-system-misc (RISC-V),
# рантайм-либы Verilator-моделей, procps.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git ca-certificates \
        make g++ perl python3 \
        qemu-system-misc \
        zlib1g libfl2 \
        procps \
    && rm -rf /var/lib/apt/lists/*

COPY --from=spike-builder /opt/riscv /opt/riscv
COPY --from=verilator-builder /opt/verilator /opt/verilator

# xPack toolchain 15.2.0 (newlib + nano.specs + rv32 multilib) — тарболл лежит
# в контексте сборки (жёсткая ссылка на ~/Work/TOOLS/...). Симлинки
# riscv64-unknown-elf-* -> riscv-none-elf-*: префикс, который ждут SCR1
# Makefile (CROSS_PREFIX по умолчанию) и tb (хардкод riscv64-unknown-elf-readelf).
COPY xpack-riscv-none-elf-gcc-*-linux-x64.tar.gz /tmp/xpack.tar.gz
RUN mkdir -p /opt/xpack-dist \
    && tar -xzf /tmp/xpack.tar.gz -C /opt/xpack-dist --strip-components=1 \
    && rm /tmp/xpack.tar.gz \
    && ln -sfn /opt/xpack-dist /opt/xpack \
    && for t in /opt/xpack/bin/riscv-none-elf-*; do \
         ln -sf "$t" "/usr/local/bin/riscv64-unknown-elf-$(basename "$t" | sed 's/^riscv-none-elf-//')"; \
       done \
    && riscv64-unknown-elf-gcc --version | head -1 \
    && riscv64-unknown-elf-readelf --version | head -1

# Свежий Spike — ПЕРЕД адаптерным Spike DiveFuzz в PATH (`spike` = свежий
# master; адаптерный остаётся по $spike = /opt/DiveFuzz/.../build/spike).
ENV PATH="/opt/riscv/bin:/opt/verilator/bin:/opt/xpack/bin:${PATH}" \
    VERILATOR_ROOT="/opt/verilator/share/verilator"

# SCR1 — тестовый дизайн. Клонирование строго по HTTPS (требование задания).
ARG SCR1_REPO=https://github.com/YarosLove91/scr1.git
RUN git clone ${SCR1_REPO} /opt/scr1 \
    && echo "SCR1 commit: $(git -C /opt/scr1 rev-parse HEAD) ($(git -C /opt/scr1 rev-parse --abbrev-ref HEAD))" \
    && git -C /opt/scr1 rev-parse HEAD > /opt/scr1-commit.txt \
    && cd /opt/scr1 \
    && if [ -f .gitmodules ]; then git submodule update --init --recursive; fi

# Смоук-тест: версии всех инструментов + коммит Spike (падает сборка при отсутствии).
RUN riscv64-unknown-elf-gcc --version | head -1 \
    && riscv64-unknown-elf-readelf --version | head -1 \
    && verilator --version \
    && spike --help >/dev/null 2>&1 && echo "Spike OK (fresh master)" \
    && cat /opt/riscv/share/spike-version.txt \
    && qemu-system-riscv32 --version | head -1 \
    && dtc --version \
    && python --version && python -c "import numpy, matplotlib, yaml; print('python libs OK')"

# DiveFuzz-пользователь уже существует (divefuzz, uid 1000) — переиспользуем.
RUN chown -R divefuzz:divefuzz /opt/scr1 \
    && mkdir -p /work && chown -R divefuzz:divefuzz /work

# oh-my-zsh для пользователя divefuzz (как в Docker_examples/Cascade.dockerfile,
# но без install.sh — он ставит только в $HOME текущего пользователя, поэтому
# прямой git clone): плагины autosuggestions + syntax-highlighting, дефолтный
# шелл = zsh. PATH из ENV образа наследуется zsh автоматически.
# NB: zsh/curl ставятся отдельным слоем ПОСЛЕ клона SCR1 — чтобы не сбрасывать
# кеш дорогого слоя `git submodule update --init --recursive` (~15 мин).
RUN apt-get update && apt-get install -y --no-install-recommends zsh curl \
    && rm -rf /var/lib/apt/lists/* \
    && git clone --depth 1 https://github.com/ohmyzsh/ohmyzsh.git /home/divefuzz/.oh-my-zsh \
    && git clone --depth 1 https://github.com/zsh-users/zsh-autosuggestions \
         /home/divefuzz/.oh-my-zsh/custom/plugins/zsh-autosuggestions \
    && git clone --depth 1 https://github.com/zsh-users/zsh-syntax-highlighting \
         /home/divefuzz/.oh-my-zsh/custom/plugins/zsh-syntax-highlighting \
    && cp /home/divefuzz/.oh-my-zsh/templates/zshrc.zsh-template /home/divefuzz/.zshrc \
    && sed -i 's/^plugins=(git)$/plugins=(git zsh-autosuggestions zsh-syntax-highlighting)/' /home/divefuzz/.zshrc \
    && chsh -s /usr/bin/zsh divefuzz \
    && chown -R divefuzz:divefuzz /home/divefuzz/.oh-my-zsh /home/divefuzz/.zshrc \
    && zsh --version

# -----------------------------------------------------------------------------
# Dev-инструменты: линковщик mold, SMT-решатель Z3 (+ python-биндинги в venv
# DiveFuzz), SSH-сервер для VS Code Remote-SSH. Слои добавлены В КОНЕЦ, чтобы
# не сбрасывать кеш предыдущих (клон SCR1 с подмодулями ~15 мин).
# mold — для хостовых сборок (Verilator-модели: -fuse-ld=mold); поддерживает
# и RISC-V, но SCR1-тесты по умолчанию линкуются родным ld xPack.
# -----------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        mold z3 openssh-server \
    && rm -rf /var/lib/apt/lists/* \
    && /opt/venv/bin/pip install --no-cache-dir z3-solver \
    && mold --version && z3 --version \
    && python -c "import z3; print('python z3', z3.get_version_string())"

# Настройка sshd для VS Code Remote-SSH:
#   - парольная аутентификация включена: divefuzz/divefuzz (ОБЯЗАТЕЛЬНО смените:
#     docker exec -u root -it <container> passwd divefuzz)
#   - root-логин запрещён; ключи — класть в /home/divefuzz/.ssh/authorized_keys
#     (или: ssh-copy-id -p 2222 divefuzz@localhost)
RUN printf '%s\n' \
        'PasswordAuthentication yes' \
        'KbdInteractiveAuthentication no' \
        'PermitRootLogin no' \
        > /etc/ssh/sshd_config.d/10-scr1-spike.conf \
    && echo 'divefuzz:divefuzz' | chpasswd \
    && install -d -o divefuzz -g divefuzz -m 700 /home/divefuzz/.ssh \
    && install -o divefuzz -g divefuzz -m 600 /dev/null /home/divefuzz/.ssh/authorized_keys \
    && mkdir -p /run/sshd \
    && ssh-keygen -A >/dev/null \
    && /usr/sbin/sshd -t && echo "sshd config OK"

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# riscv-pk (proxy kernel): `spike [-d] pk hello` (README riscv-isa-sim), для
# RV32 — `spike --isa=rv32imac_zicsr_zifencei [-d] pk32 hello32`.
# NB: spike ищет payload НЕ через PATH, а только в `.` и в
# <prefix>/<target>/bin = /opt/riscv/riscv64-unknown-elf/bin/ — симлинки pk/pk32
# кладём и туда (для bare `spike pk ...`), и в /usr/local/bin (для путей).
# Смоук: реальный запуск C-hello (newlib xPack, HTIF) через pk на rv64 и pk32
# на rv32 — доказывает, что pk грузится и исполняет payload.
COPY --from=pk-builder /opt/riscv-pk /opt/riscv-pk
COPY --from=pk-builder /opt/riscv-pk32 /opt/riscv-pk32
RUN mkdir -p /opt/riscv/riscv64-unknown-elf/bin \
    && ln -s /opt/riscv-pk/riscv-none-elf/bin/pk  /opt/riscv/riscv64-unknown-elf/bin/pk \
    && ln -s /opt/riscv-pk32/riscv-none-elf/bin/pk /opt/riscv/riscv64-unknown-elf/bin/pk32 \
    && ln -s /opt/riscv-pk/riscv-none-elf/bin/pk  /usr/local/bin/pk \
    && ln -s /opt/riscv-pk32/riscv-none-elf/bin/pk /usr/local/bin/pk32 \
    && printf '#include <stdio.h>\nint main(){printf("pk hello\\n");return 0;}\n' > /tmp/hello.c \
    && riscv64-unknown-elf-gcc -O2 -march=rv64imac_zicsr_zifencei -mabi=lp64 \
         /tmp/hello.c -o /tmp/hello64.elf \
    && riscv64-unknown-elf-gcc -O2 -march=rv32imac_zicsr_zifencei -mabi=ilp32 \
         /tmp/hello.c -o /tmp/hello32.elf \
    && spike pk /tmp/hello64.elf \
    && spike --isa=rv32imac_zicsr_zifencei pk32 /tmp/hello32.elf \
    && rm -f /tmp/hello.c /tmp/hello64.elf /tmp/hello32.elf \
    && echo "pk smoke OK (rv64 pk + rv32 pk32)"

EXPOSE 22

# По умолчанию root: entrypoint поднимает sshd (нужен root) и сбрасывает
# привилегии до divefuzz перед CMD (интерактивный zsh с oh-my-zsh).
#   docker run --rm -it -p 2222:22 scr1-spike-verif:latest
#   VS Code: Remote-SSH: Connect to Host... -> ssh://divefuzz@localhost:2222
#   (пароль divefuzz). vscode-server ставится в /home/divefuzz/.vscode-server
#   (слой контейнера; для персистентности: -v scr1-home:/home/divefuzz).
# docker exec идёт МИНУЯ entrypoint: docker exec -u divefuzz -it <container> zsh
USER root
WORKDIR /work
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["/bin/zsh"]
