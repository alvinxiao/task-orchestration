<img src="assets/icon.svg" width="64" height="64" alt="">

# task-orchestration

Python library and JSON CLI that assign tasks to qualified employees and order
their work, backed by OR-Tools CP-SAT. The scheduling rules and default
objective follow the Timefold task-assigning quickstart.

## Rules

- A task's type lists required skills; only employees with all of them are eligible.
- An employee's affinity for the task's customer scales the duration:
  NONE=4, LOW=3, MEDIUM=2, HIGH=1. Missing affinity means NONE.
- Each task runs once, never before its earliest start, and an employee's tasks
  never overlap.
- Objective: the sum of squared employee finish times plus task finish times
  weighted 4 (CRITICAL), 2 (MAJOR), 1 (MINOR). Tasks without an eligible
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
with reasons, makespan, objective components, best bound, and elapsed time.
An `UNKNOWN` result means no proven answer, not infeasibility.

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
the time limit is positive. Invalid data raises field-specific validation
errors before the solver runs.

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
with at least one eligible employee is always assignable. The reported
makespan is the true maximum employee finish; the objective's squared-finish
term is the reference's own soft cost and is reported separately. Returned
schedules are compacted to earliest feasible starts and all metrics are
recomputed from the returned schedule.

## Limits and statuses

The time limit covers model preparation, search, and schedule extraction.
Search receives only the remaining budget. Deadline checks stop preparation or
extraction with UNKNOWN and no partial schedule. Individual Python operations,
CP-SAT calls, and serialization are not interruptible at exact deadlines, so
this is a cooperative budget rather than a hard wall-clock guarantee.
Elapsed time includes schedule extraction but excludes CLI serialization.

Only OPTIMAL and FEASIBLE carry a usable schedule. Zero metrics for other
statuses are placeholders, not a claim that all work finished at time zero.
Unassigned entries identify known skill gaps; on UNKNOWN they may be incomplete.

Numeric limits derive from the modeled integer domains. Unsafe bounds raise
ValueError in the library and produce exit code 2 in the CLI. Optimal bounds
use the exact integer objective. A feasible lower bound is omitted when it
exceeds the floating-point API's exact integer range.
