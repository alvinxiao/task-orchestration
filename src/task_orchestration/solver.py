
from __future__ import annotations

import time

from ortools.sat.python import cp_model

from .domain import (
    AFFINITY_MULTIPLIER,
    DEFAULT_AFFINITY,
    PRIORITY_WEIGHT,
    Affinity,
    Employee,
    EmployeeSchedule,
    ObjectiveComponents,
    PlanningRequest,
    SolveResult,
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


def _eligible_employees(task: Task, task_type: TaskType, employees: list[Employee]) -> list[Employee]:
    return [employee for employee in employees if task_type.required_skills <= employee.skills]


def _employee_affinity(employee: Employee, task: Task) -> Affinity:
    return employee.customer_affinities.get(task.customer_id, DEFAULT_AFFINITY)


def _compact(
    scheduled: list[tuple[str, int, int]], earliest_starts: dict[str, int]
) -> list[TaskAssignment]:
    ordered = sorted(scheduled, key=lambda item: item[1])
    result: list[TaskAssignment] = []
    now = 0
    for task_id, solver_start, duration in ordered:
        start = max(now, earliest_starts[task_id])
        result.append(
            TaskAssignment(task_id=task_id, start=start, finish=start + duration, duration=duration)
        )
        now = start + duration
    return result


def solve(request: PlanningRequest) -> SolveResult:
    """Solve a validated planning request. The single public solve operation."""
    started = time.perf_counter()

    def no_schedule(status="UNKNOWN", unassigned=()):
        return SolveResult(
            status=status, assignments=[], unassigned=list(unassigned), makespan=0,
            objective=ObjectiveComponents(
                squared_employee_finish_cost=0, weighted_task_completion_cost=0
            ), best_bound=None, elapsed_seconds=time.perf_counter() - started,
        )

    def expired():
        return time.perf_counter() - started >= request.options.time_limit_seconds

    task_type_by_id = {task_type.id: task_type for task_type in request.task_types}

    eligible: dict[str, list[Employee]] = {}
    duration_of: dict[tuple[str, str], int] = {}
    for task in request.tasks:
        if expired():
            return no_schedule()
        task_type = task_type_by_id[task.task_type_id]
        candidates = _eligible_employees(task, task_type, request.employees)
        eligible[task.id] = candidates
        for employee in candidates:
            if expired():
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
    objective_bound = len(request.employees) * horizon**2 + sum(
        PRIORITY_WEIGHT[task.priority] * horizon * len(eligible[task.id])
        for task in request.tasks
    )
    if horizon**2 > _CP_SAT_MAX_INT // 2 or objective_bound > _CP_SAT_MAX_INT // 2:
        raise ValueError("planning horizon and objective domains exceed CP-SAT integer limits")

    unassigned_pre: list[UnassignedTask] = []
    for task in request.tasks:
        if expired():
            return no_schedule()
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
    employee_finish: dict[str, cp_model.IntVar] = {
        employee.id: model.NewIntVar(0, horizon, f"employee_finish_{employee.id}")
        for employee in request.employees
    }

    presence_of: dict[str, list[tuple[Employee, cp_model.IntVar]]] = {}
    start_of: dict[tuple[str, str], cp_model.IntVar] = {}
    employee_intervals: dict[str, list[cp_model.IntervalVar]] = {}
    weighted_costs: list[cp_model.IntVar] = []

    for task in request.tasks:
        if expired():
            return no_schedule()
        if not eligible[task.id]:
            continue
        weight = PRIORITY_WEIGHT[task.priority]
        for employee in eligible[task.id]:
            if expired():
                return no_schedule()
            duration = duration_of[(task.id, employee.id)]
            suffix = f"{task.id}_{employee.id}"
            presence = model.NewBoolVar(f"present_{suffix}")
            start = model.NewIntVar(task.earliest_start, horizon, f"start_{suffix}")
            finish = model.NewIntVar(task.earliest_start + duration, horizon, f"finish_{suffix}")
            interval = model.NewOptionalIntervalVar(
                start, duration, finish, presence, f"interval_{suffix}"
            )
            model.Add(employee_finish[employee.id] >= finish).OnlyEnforceIf(presence)
            weighted = model.NewIntVar(0, weight * horizon, f"weighted_{suffix}")
            model.Add(weighted == weight * finish).OnlyEnforceIf(presence)
            model.Add(weighted == 0).OnlyEnforceIf(presence.Not())
            weighted_costs.append(weighted)
            employee_intervals.setdefault(employee.id, []).append(interval)
            presence_of.setdefault(task.id, []).append((employee, presence))
            start_of[(task.id, employee.id)] = start
        model.AddExactlyOne([presence for _, presence in presence_of[task.id]])

    for employee in request.employees:
        model.AddNoOverlap(employee_intervals.get(employee.id, []))

    squared_costs: list[cp_model.IntVar] = []
    for employee in request.employees:
        finish = employee_finish[employee.id]
        squared = model.NewIntVar(0, horizon * horizon, f"squared_{employee.id}")
        model.AddMultiplicationEquality(squared, [finish, finish])
        squared_costs.append(squared)

    model.Minimize(sum(squared_costs) + sum(weighted_costs))

    validation_error = model.Validate()
    if validation_error:
        raise ValueError(f"invalid solver model or numeric bounds: {validation_error}")
    if expired():
        return no_schedule(unassigned=unassigned_pre)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(0.0, request.options.time_limit_seconds - (time.perf_counter() - started))
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    status_code = solver.Solve(model)
    status = _STATUS_NAMES.get(status_code, "UNKNOWN")
    if status not in ("OPTIMAL", "FEASIBLE"):
        return no_schedule(status, unassigned_pre)

    employee_schedules: list[EmployeeSchedule] = []
    makespan = 0
    earliest_starts = {task.id: task.earliest_start for task in request.tasks}
    scheduled_by_employee = {employee.id: [] for employee in request.employees}
    for task in request.tasks:
        for candidate, presence in presence_of.get(task.id, []):
            if expired():
                return no_schedule(unassigned=unassigned_pre)
            if solver.Value(presence):
                scheduled_by_employee[candidate.id].append((
                    task.id, solver.Value(start_of[(task.id, candidate.id)]),
                    duration_of[(task.id, candidate.id)],
                ))
    for employee in request.employees:
        if expired():
            return no_schedule(unassigned=unassigned_pre)
        compacted = _compact(scheduled_by_employee[employee.id], earliest_starts)
        if compacted:
            makespan = max(makespan, compacted[-1].finish)
        employee_schedules.append(EmployeeSchedule(employee_id=employee.id, tasks=compacted))

    task_by_id = {task.id: task for task in request.tasks}
    squared_total = sum(s.tasks[-1].finish**2 for s in employee_schedules if s.tasks)
    weighted_total = sum(
        PRIORITY_WEIGHT[task_by_id[a.task_id].priority] * a.finish
        for s in employee_schedules
        for a in s.tasks
    )

    return SolveResult(
        status=status,
        assignments=employee_schedules,
        unassigned=unassigned_pre,
        makespan=makespan,
        objective=ObjectiveComponents(
            squared_employee_finish_cost=squared_total,
            weighted_task_completion_cost=weighted_total,
        ),
        best_bound=(squared_total + weighted_total if status == "OPTIMAL" else
                    int(solver.BestObjectiveBound()) if abs(solver.BestObjectiveBound()) < 2**53 else None),
        elapsed_seconds=time.perf_counter() - started,
    )
