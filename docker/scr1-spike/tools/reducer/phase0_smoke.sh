#!/usr/bin/env bash
# Дым-тест Фазы 0 (без симуляций): IR + ground truth static + identity-срез + hex-сравнение.
set -euo pipefail
: "${SCR1_DIR:?}"
: "${WT:?}"
cd "$WT/docker/scr1-spike/tools/reducer"
exec python3 - <<'PY'
import json, os, sys, time
sys.path.insert(0, os.getcwd())
from redlib.env import Env
from redlib.ir import IR
from redlib.slicer import SliceBuild, same_bytes

env = Env()
print("BLD =", env.bld)
t0 = time.monotonic()
ir = IR(env, env.base_elf)
s = ir.summary()
print("IR built in %.1fs" % (time.monotonic() - t0))
print(json.dumps({k: (hex(v) if isinstance(v, int) and v > 4096 else v) for k, v in s.items() if k != "sections"}, indent=1))
assert s["static_total"] == 3370, s["static_total"]
assert s["trigger_start"] == 0x4820EE and s["trigger_end"] == 0x48211A
assert s["trigger_static_idx"] == 2924, s["trigger_static_idx"]
print("static ground truth OK")
print("service points:", {k: (hex(v) if v else v) for k, v in ir.service_points().items()})

out = os.path.join(env.out, "smoke")
t0 = time.monotonic()
sb = SliceBuild(env, env.base_elf)
art = sb.build(out, "idn")
base_hex = sb.base_hex(out)
dt = time.monotonic() - t0
ident = same_bytes(art["hex"], base_hex)
print("slice build %.2fs, hex identical: %s" % (dt, ident))
if not ident:
    la = open(art["hex"]).read().splitlines()
    lb = open(base_hex).read().splitlines()
    print("lines slice=%d base=%d" % (len(la), len(lb)))
    for i in range(max(len(la), len(lb))):
        x = la[i] if i < len(la) else "<EOF>"
        y = lb[i] if i < len(lb) else "<EOF>"
        if x != y:
            print("first diff line %d:\n slice=%s\n base =%s" % (i + 1, x, y))
            break
    sys.exit(2)
print("SMOKE_OK")
PY
