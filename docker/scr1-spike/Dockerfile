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
#
# Сборка:  docker build --progress=plain -t scr1-spike-verif:latest docker/scr1-spike \
#            2>&1 | tee docker/scr1-spike/logs/build.log
# Запуск:  docker run --rm -it scr1-spike-verif:latest
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
# Stage 3: runtime (база — DiveFuzz: python/venv/библиотеки сохраняются)
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

USER divefuzz
WORKDIR /work
# Сбрасываем ENTRYPOINT DiveFuzz (divefuzz --help) — образ для интерактивной верификации.
ENTRYPOINT []
CMD ["/bin/bash"]
