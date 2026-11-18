# Verification

Run on Windows with CPython 3.12 and uv at `%LOCALAPPDATA%\t3-tools\uv\uv.exe`.

2026-11-17: `uv run pytest -q` passes 45 tests on branch `feat/strict-priority-scheduling`. `uv run task-assign examples/sample.json` returns OPTIMAL, provisional false, proven priorities CRITICAL, HIGH, MEDIUM, LOW, makespan 180, stage values 30/180/0/180 and fairness 49300. The rebuilt wheel installed in a fresh virtual environment returns the same status and makespan via the installed `task-assign` CLI.

## What this round changed

The mixed weighted objective (squared finish costs plus 4/2/1 priority weights) was replaced by strict lexicographic scheduling: CRITICAL, HIGH, MEDIUM, LOW stages each minimize their priority's total completion time, run to proven OPTIMAL, and lock the exact integer value before the next stage. A final fairness stage minimizes the sum of squared per-employee assigned work minutes among schedules that keep every locked total. Priorities are canonical CRITICAL, HIGH, MEDIUM, LOW; legacy MAJOR and MINOR inputs normalize to HIGH and LOW at the input boundary, and the arbitrary PRIORITY_WEIGHT export was removed.

Tests migrated to an independent lexicographic oracle over exhaustive assignment and order enumeration comparing the tuple (critical, high, medium, low, squared loads) built from test-local literals. New cases prove a lower priority cannot worsen a higher aggregate, permutations are allowed at a fixed total, fairness only applies after all totals are locked, affinity changes assigned work minutes, a controlled FEASIBLE first stage stops provisional, a later UNKNOWN stage retains the prior incumbent, one shared budget covers setup and every stage, and validation runs per stage. No behavioral test was weakened; obsolete weighted-objective tests were replaced, not deleted.

## Replanning round (2026-11-18, branch feat/operational-replanning)

Added operational replanning: an additive typed `ReplanningContext` on the request (default `current_time=0`, so old requests validate and solve unchanged, stage list included), fixed intervals for in-progress and committed work, and an optional STABILITY stage. 69 tests pass (`uv run pytest -q`), including 24 new replanning cases at the public solve boundary: urgent arrival, no past starts, in-progress not rescheduled with actual start preserved, remaining-minute occupancy and remaining-only fairness, completed exclusion, committed locking, invalid execution states at the boundary, fixed-interval conflicts, stability after fairness is locked, old-request compatibility, and incumbent retention when a later stage hits the deadline. `uv run python examples/replan.py` runs the first-solve-then-replan example: the running task keeps its actual start with finish 60 and duration 20, the urgent CRITICAL job starts at current time 40 on the free employee, and stability reports the one pending job whose start changed. The rebuilt wheel smoke test and CLI sample still return OPTIMAL.

Documented limits: in-progress skills are grandfathered (the employee must still exist); stability tracks only previous pending tasks; completed work contributes zero to all metrics by design; the stability stage locks nothing after itself because it is last.

## Deferred and documented limits

- Returned schedules preserve the solver's chosen starts instead of post-hoc compaction, so every locked priority sum is preserved exactly. Proving a compaction retains locked sums was not needed because starts are preserved.
- Fairness treats employee capacity as equal. Normalizing loads by actual capacity is deferred until shifts or calendars exist.
- Extraction runs past the deadline once a stage has solved; dropping the incumbent there would discard all proven work. This cooperative-budget overhead is documented in the README.
- A non-proven stage's bound passes through the floating-point solver API and is conservative; proven stages report exact integer values and bounds.
- The wheel was rebuilt with `uv build` and the installed `task-assign examples/sample.json` CLI run from a fresh virtual environment returned OPTIMAL, provisional false, makespan 180.
