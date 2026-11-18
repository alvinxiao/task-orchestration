
from __future__ import annotations

import time

from ortools.sat.python import cp_model

from .domain import (
    AFFINITY_MULTIPLIER,
    DEFAULT_AFFINITY,
    PRIORITY_ORDER,
    Affinity,
    Employee,
    EmployeeSchedule,
    ObjectiveSummary,
    PlanningRequest,
    Priority,
    SolveResult,
    StageRecord,
    Task,
    TaskAssignment,
    TaskType,
    UnassignedTask,
)

_CP_SAT_MAX_INT = 2**63 - 1

_STATUS_NAMES = {
    cp_model.OPTIMAL: "OPTIMAL",
    cp_model.FEASIBLE: "FEASIBLE",
    cp_model.INFEASIBLE: "INFEASIBLE",
    cp_model.MODEL_INVALID: "MODEL_INVALID",
    cp_model.UNKNOWN: "UNKNOWN",
}

FAIRNESS_STAGE = "FAIRNESS"


def _eligible_employees(task: Task, task_type: TaskType, employees: list[Employee]) -> list[Employee]:
    return [employee for employee in employees if task_type.required_skills <= employee.skills]


def _employee_affinity(employee: Employee, task: Task) -> Affinity:
    return employee.customer_affinities.get(task.customer_id, DEFAULT_AFFINITY)


def _stage_not_run(name: str) -> StageRecord:
    return StageRecord(name=name, status="NOT_RUN", proven=False, value=None, bound=None)


def _summary_from_schedule(
    request: PlanningRequest,
    schedules: list[EmployeeSchedule],
    duration_by_task: dict[str, int],
) -> ObjectiveSummary:
    totals = {priority.value: 0 for priority in PRIORITY_ORDER}
    priority_of = {task.id: task.priority.value for task in request.tasks}
    for schedule in schedules:
        for assignment in schedule.tasks:
            totals[priority_of[assignment.task_id]] += assignment.finish
    work_minutes = {}
    squared = 0
    for schedule in schedules:
        load = sum(duration_by_task[assignment.task_id] for assignment in schedule.tasks)
        work_minutes[schedule.employee_id] = load
        squared += load**2
    return ObjectiveSummary(
        priority_completion_totals=totals,
        employee_work_minutes=work_minutes,
        squared_load_cost=squared,
    )


def solve(request: PlanningRequest) -> SolveResult:
    """Solve a validated planning request. The single public solve operation.

    Strict lexicographic stages over priorities CRITICAL, HIGH, MEDIUM, LOW,
    each minimizing the sum of assigned task finish times, then a final
    fairness stage minimizing the sum of squared per-employee assigned work
    minutes. Each stage runs to proven OPTIMAL before the next; a FEASIBLE or
    UNKNOWN stage stops with a provisional result and the last incumbent.
    """
    started = time.perf_counter()

    def remaining():
        return request.options.time_limit_seconds - (time.perf_counter() - started)

    stage_names = [priority.value for priority in PRIORITY_ORDER] + [FAIRNESS_STAGE]

    def no_schedule(status="UNKNOWN", unassigned=(), records=None):
        return SolveResult(
            status=status,
            provisional=True,
            proven_priorities=[],
            stages=records if records is not None else [_stage_not_run(name) for name in stage_names],
            assignments=[],
            unassigned=list(unassigned),
            makespan=0,
            objective=ObjectiveSummary(
                priority_completion_totals={priority.value: 0 for priority in PRIORITY_ORDER},
                employee_work_minutes={employee.id: 0 for employee in request.employees},
                squared_load_cost=0,
            ),
            elapsed_seconds=time.perf_counter() - started,
        )

    task_type_by_id = {task_type.id: task_type for task_type in request.task_types}

    eligible: dict[str, list[Employee]] = {}
    duration_of: dict[tuple[str, str], int] = {}
    for task in request.tasks:
        if remaining() <= 0:
            return no_schedule()
        task_type = task_type_by_id[task.task_type_id]
        candidates = _eligible_employees(task, task_type, request.employees)
        eligible[task.id] = candidates
        for employee in candidates:
            if remaining() <= 0:
                return no_schedule()
            affinity = _employee_affinity(employee, task)
            duration_of[(task.id, employee.id)] = (
                task_type.base_duration * AFFINITY_MULTIPLIER[affinity]
            )

    max_durations = [
        max(duration_of[(task.id, employee.id)] for employee in eligible[task.id])
        for task in request.tasks
        if eligible[task.id]
    ]
    max_release = max(
        (task.earliest_start for task in request.tasks if eligible[task.id]),
        default=0,
    )
    horizon = max_release + sum(max_durations)

    load_bound = len(request.employees) * horizon**2
    completion_bound = max(
        (sum(1 for task in request.tasks if eligible[task.id] and task.priority == priority)
         for priority in PRIORITY_ORDER),
        default=0,
    ) * horizon
    if horizon**2 > _CP_SAT_MAX_INT // 2 or load_bound > _CP_SAT_MAX_INT // 2 or completion_bound > _CP_SAT_MAX_INT // 2:
        raise ValueError("planning horizon and stage objective domains exceed CP-SAT integer limits")

    unassigned_pre: list[UnassignedTask] = []
    for task in request.tasks:
        if not eligible[task.id]:
            if not request.employees:
                unassigned_pre.append(UnassignedTask(task_id=task.id, reason="no employees defined"))
            else:
                unassigned_pre.append(
                    UnassignedTask(
                        task_id=task.id,
                        reason=f"no employee has the skills required by task type {task.task_type_id!r}",
                    )
                )

    model = cp_model.CpModel()

    presence_of: dict[str, list[tuple[Employee, cp_model.IntVar]]] = {}
    start_of: dict[tuple[str, str], cp_model.IntVar] = {}
    employee_intervals: dict[str, list[cp_model.IntervalVar]] = {}
    task_finish: dict[str, cp_model.IntVar] = {}
    load_of: dict[str, cp_model.IntVar] = {}
    total_of: dict[str, cp_model.IntVar] = {}
    squared_loads: list[cp_model.IntVar] = []
    load_terms: dict[str, list] = {employee.id: [] for employee in request.employees}

    for task in request.tasks:
        if not eligible[task.id]:
            continue
        finish = model.NewIntVar(task.earliest_start, horizon, f"finish_{task.id}")
        task_finish[task.id] = finish
        for employee in eligible[task.id]:
            duration = duration_of[(task.id, employee.id)]
            suffix = f"{task.id}_{employee.id}"
            presence = model.NewBoolVar(f"present_{suffix}")
            start = model.NewIntVar(task.earliest_start, horizon, f"start_{suffix}")
            pair_finish = model.NewIntVar(task.earliest_start + duration, horizon, f"pf_{suffix}")
            interval = model.NewOptionalIntervalVar(
                start, duration, pair_finish, presence, f"interval_{suffix}"
            )
            model.Add(finish == pair_finish).OnlyEnforceIf(presence)
            load_terms[employee.id].append(duration * presence)
            employee_intervals.setdefault(employee.id, []).append(interval)
            presence_of.setdefault(task.id, []).append((employee, presence))
            start_of[(task.id, employee.id)] = start
        model.AddExactlyOne([presence for _, presence in presence_of[task.id]])

    for employee in request.employees:
        model.AddNoOverlap(employee_intervals.get(employee.id, []))
        load = model.NewIntVar(0, horizon, f"load_{employee.id}")
        model.Add(load == sum(load_terms[employee.id]))
        load_of[employee.id] = load
        squared = model.NewIntVar(0, horizon * horizon, f"squared_load_{employee.id}")
        model.AddMultiplicationEquality(squared, [load, load])
        squared_loads.append(squared)

    for priority in PRIORITY_ORDER:
        tasks_p = [
            task for task in request.tasks
            if eligible[task.id] and task.priority == priority
        ]
        total = model.NewIntVar(0, len(tasks_p) * horizon, f"total_{priority.value}")
        model.Add(total == sum(task_finish[task.id] for task in tasks_p))
        total_of[priority.value] = total

    stage_vars: list[tuple[str, cp_model.IntVar | None]] = [
        (priority.value, total_of[priority.value] if any(
            eligible[task.id] and task.priority == priority for task in request.tasks
        ) else None)
        for priority in PRIORITY_ORDER
    ]
    fairness_objective = sum(squared_loads) if squared_loads else None
    stage_vars.append((FAIRNESS_STAGE, fairness_objective))

    records: list[StageRecord] = []
    proven_priorities: list[str] = []
    incumbent: tuple[list[EmployeeSchedule], int] | None = None
    provisional = False

    def extract() -> tuple[list[EmployeeSchedule], int]:
        # Runs past the deadline once a stage solved: dropping the incumbent
        # here would discard all proven work.
        employee_schedules: list[EmployeeSchedule] = []
        makespan = 0
        scheduled_by_employee = {employee.id: [] for employee in request.employees}
        for task in request.tasks:
            for candidate, presence in presence_of.get(task.id, []):
                if solver.Value(presence):
                    duration = duration_of[(task.id, candidate.id)]
                    start = solver.Value(start_of[(task.id, candidate.id)])
                    scheduled_by_employee[candidate.id].append(
                        TaskAssignment(
                            task_id=task.id,
                            start=start,
                            finish=start + duration,
                            duration=duration,
                        )
                    )
        for employee in request.employees:
            tasks = sorted(scheduled_by_employee[employee.id], key=lambda item: item.start)
            if tasks:
                makespan = max(makespan, tasks[-1].finish)
            employee_schedules.append(EmployeeSchedule(employee_id=employee.id, tasks=tasks))
        return employee_schedules, makespan

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0

    for name, stage_objective in stage_vars:
        if stage_objective is None:
            records.append(StageRecord(name=name, status="OPTIMAL", proven=True, value=0, bound=0))
            if name != FAIRNESS_STAGE:
                proven_priorities.append(name)
            continue
        if remaining() <= 0:
            records.append(_stage_not_run(name))
            provisional = True
            break
        model.Minimize(stage_objective)
        validation_error = model.Validate()
        if validation_error:
            raise ValueError(f"invalid solver model or numeric bounds: {validation_error}")
        if remaining() <= 0:
            records.append(_stage_not_run(name))
            provisional = True
            break
        solver.parameters.max_time_in_seconds = remaining()
        status_code = solver.Solve(model)
        status = _STATUS_NAMES.get(status_code, "UNKNOWN")
        if status == "OPTIMAL":
            value = int(solver.Value(stage_objective))
            records.append(StageRecord(name=name, status=status, proven=True, value=value, bound=value))
            if name != FAIRNESS_STAGE:
                proven_priorities.append(name)
                model.Add(stage_objective == value)
            incumbent = extract()
            continue
        if status == "FEASIBLE":
            value = int(solver.Value(stage_objective))
            bound = solver.BestObjectiveBound()
            bound_record = int(bound) if abs(bound) < 2**53 else None
            records.append(StageRecord(name=name, status=status, proven=False, value=value, bound=bound_record))
            incumbent = extract()
            provisional = True
            break
        records.append(StageRecord(name=name, status=status, proven=False, value=None, bound=None))
        provisional = True
        break

    if incumbent is None:
        if not provisional:
            # Every stage was trivially proven with nothing to schedule.
            return SolveResult(
                status="OPTIMAL",
                provisional=False,
                proven_priorities=proven_priorities,
                stages=records,
                assignments=[],
                unassigned=unassigned_pre,
                makespan=0,
                objective=ObjectiveSummary(
                    priority_completion_totals={priority.value: 0 for priority in PRIORITY_ORDER},
                    employee_work_minutes={employee.id: 0 for employee in request.employees},
                    squared_load_cost=0,
                ),
                elapsed_seconds=time.perf_counter() - started,
            )
        status_name = records[-1].status if records else "UNKNOWN"
        return no_schedule(
            status=status_name if status_name in ("INFEASIBLE", "MODEL_INVALID", "UNKNOWN") else "UNKNOWN",
            unassigned=unassigned_pre,
            records=records + [_stage_not_run(name) for name in stage_names[len(records):]],
        )

    schedules, makespan = incumbent
    duration_by_task = {
        assignment.task_id: assignment.duration
        for schedule in schedules for assignment in schedule.tasks
    }
    return SolveResult(
        status="OPTIMAL" if not provisional else "FEASIBLE",
        provisional=provisional,
        proven_priorities=proven_priorities,
        stages=records + [_stage_not_run(name) for name in stage_names[len(records):]],
        assignments=schedules,
        unassigned=unassigned_pre,
        makespan=makespan,
        objective=_summary_from_schedule(request, schedules, duration_by_task),
        elapsed_seconds=time.perf_counter() - started,
    )
