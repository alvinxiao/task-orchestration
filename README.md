<img src="assets/icon.svg" width="64" height="64" alt="">

# task-orchestration

Python library and JSON CLI that assign tasks to qualified employees and order
their work, backed by OR-Tools CP-SAT. Tasks are scheduled by strict
lexicographic priority, then balanced across employees.

## Rules

- A task's type lists required skills; only employees with all of them are eligible.
- An employee's affinity for the task's customer scales the duration:
  NONE=4, LOW=3, MEDIUM=2, HIGH=1. Missing affinity means NONE.
- Each task runs once, never before its earliest start, and an employee's tasks
  never overlap. Every task with an eligible employee is assigned.
- Priorities are CRITICAL, HIGH, MEDIUM, LOW. Legacy input values MAJOR and
  MINOR are accepted and normalized to HIGH and LOW.
- Objective, optimized strictly in order: minimize the total completion time
  (sum of finish times) of CRITICAL tasks, then HIGH, then MEDIUM, then LOW,
  each proven optimal and locked before the next stage. Finally, among
  schedules that keep every locked total, minimize the sum of squared
  per-employee assigned work minutes for fairness. Tasks without an eligible
  employee are reported as unassigned.

## Install

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync --locked
```

## Library use

```python
from task_orchestration import PlanningRequest, solve

request = PlanningRequest.model_validate_json(open("examples/sample.json").read())
result = solve(request)
print(result.status, result.makespan, result.objective)
```

`solve(request)` is the single public operation. It returns a structured
`SolveResult` with status (`OPTIMAL`, `FEASIBLE`, `INFEASIBLE`,
`MODEL_INVALID`, `UNKNOWN`), per-employee ordered schedules, unassigned tasks
with reasons, makespan, per-priority completion totals, per-employee work
minutes, the squared load cost, one stage record per objective, and elapsed
time. An `UNKNOWN` result means no proven answer, not infeasibility.

A result is provisional unless every stage finished proven optimal. A
FEASIBLE or UNKNOWN stage stops the sequence: the last proven priorities are
listed in `proven_priorities`, the retained schedule is the last incumbent,
and `provisional` is true. Do not treat a provisional result as a strict
lexicographic optimum.

## CLI use

```sh
uv run task-assign examples/sample.json
```

The CLI reads a JSON planning request from the file argument (or stdin) and
prints the JSON result. Exit codes: 0 solved, 1 no schedule produced
(INFEASIBLE, MODEL_INVALID, or UNKNOWN), 2 invalid input.

## Input shape

```json
{
  "employees": [
    {"id": "e1", "name": "Ann", "skills": ["welding"], "customer_affinities": {"c1": "HIGH"}}
  ],
  "customers": [{"id": "c1", "name": "Alpha Co"}],
  "task_types": [{"id": "t_weld", "base_duration": 30, "required_skills": ["welding"]}],
  "tasks": [
    {"id": "task1", "task_type_id": "t_weld", "customer_id": "c1", "earliest_start": 0, "priority": "CRITICAL"}
  ],
  "options": {"time_limit_seconds": 5.0}
}
```

IDs must be unique within each list, references must resolve, base durations
are positive integers, earliest starts are nonnegative integer minutes, and
the time limit is positive. Priorities accept CRITICAL, HIGH, MEDIUM, LOW, and
the legacy aliases MAJOR (HIGH) and MINOR (LOW). Invalid data raises
field-specific validation errors before the solver runs.

## Development

```sh
uv sync --locked
uv run pytest
```

Reproducible development settings: the solver runs single-threaded with a
fixed random seed, and dependency versions are pinned in `uv.lock`. Tied
schedules may still differ across solver versions.

## Model assumptions

There is no deadline, capacity horizon, or employee calendar, so every task
with at least one eligible employee is always assignable. Employee capacity
is treated as equal when balancing work minutes; normalizing loads by actual
capacity is deferred until shifts or calendars exist. The reported makespan
is the true maximum employee finish. Returned schedules preserve the solver's
chosen starts (sorted by start); no post-hoc compaction runs, so every locked
priority total is preserved exactly in the returned schedule.

## Limits and statuses

One time budget covers model preparation, every stage's search, and schedule
extraction. Each stage's search receives only the remaining budget. Deadline
checks stop preparation or a later stage with UNKNOWN; once a stage has
solved, extraction runs to completion even past the deadline because dropping
the incumbent there would discard all proven work. Individual Python
operations, CP-SAT calls, and serialization are not interruptible at exact
deadlines, so this is a cooperative budget rather than a hard wall-clock
guarantee. Elapsed time includes schedule extraction but excludes CLI
serialization.

Only OPTIMAL and FEASIBLE carry a usable schedule. Zero metrics for other
statuses are placeholders, not a claim that all work finished at time zero.
Unassigned entries identify known skill gaps; on UNKNOWN they may be
incomplete.

Stage values are exact integers; a non-proven stage's bound is conservative
because it passes through the floating-point solver API. Proven stages report
the exact integer value and bound. Numeric limits derive from the modeled
stage domains, and the model is validated before each stage's solve. Unsafe
bounds raise ValueError in the library and produce exit code 2 in the CLI.
