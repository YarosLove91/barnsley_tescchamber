# Reference: Cascade reducer (копии файлов cascade-meta для порта)

Скопировано пользователем-разрешённым образом из сабмодуля `cascade-meta/`
(git@github.com:cascade-artifacts-designs/cascade-meta.git, gitlink c3de482)
для использования как РЕФЕРЕНС при портировании алгоритмов редуктора.

* `reduce.py` (868 строк) — оркестрация `reduce_program:640`, оракул `is_mismatch:254`,
  `gen_reduced_elf:170`, бинпоиски `_find_failing_bb:313` / `_find_failing_instr_in_bb:408` /
  `_find_pillar_bb:357` / `_find_pillar_instr:465`, context-setter вход
  `_save_ctx_and_jump_to_pillar_specific_instr:32`.
* `contextreplay.py` — `SavedContext:56`, `gen_context_setter:78` (синтез восстанавливающего
  блока: GPR/FPR/CSR/privilege/память).
* `spikeresolution.py` — `spike_resolution:270`, `gen_ctx_regdump_reqs:90`,
  `run_trace_regs_at_pc_locs` (дампы состояния Spike в произвольных точках).
* `fuzzsim.py` — `runtest_simulator:154` (прогон RTL + сравнение финальных регистров).
* `LICENSE.txt` — GPL-3.0 (Copyright 2023 Flavien Solt, ETH Zurich).

Внимание: лицензия GPL-3.0. Файлы лежат как референс; портируемые реализации
(redlib/*) пишутся заново под наш IR/оракул. Распространение производных —
с учётом обязательств GPL-3.0 (по решению пользователя репо).
