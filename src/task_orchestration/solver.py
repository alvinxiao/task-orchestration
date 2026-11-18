
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
    ReplanningChange,
    SolveResult,
    StabilityMetrics,
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
STABILITY_STAGE = "STABILITY"


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
    each minimizing the sum of assigned task finish times (including the fixed
    finish of in-progress and committed work), then a final fairness stage
    minimizing the sum of squared per-employee work minutes, where in-progress
    tasks count only their remaining minutes. Each stage runs to proven
    OPTIMAL and its exact value is locked before the next. With a replanning
    context carrying previous assignments, one final STABILITY stage minimizes
    the number of previous pending tasks whose employee or start changed. A
    FEASIBLE or UNKNOWN stage stops with a provisional result and the last
    incumbent.
    """
    started = time.perf_counter()

    context = request.replanning
    current_time = context.current_time
    completed_ids = set(context.completed_task_ids)
    in_progress_by_task = {record.task_id: record for record in context.in_progress}
    committed_by_task = {record.task_id: record for record in context.committed}
    task_by_id = {task.id: task for task in request.tasks}
    employee_by_id = {employee.id: employee for employee in request.employees}
    pending = [
        task for task in request.tasks
        if task.id not in completed_ids
        and task.id not in in_progress_by_task
        and task.id not in committed_by_task
    ]

    def remaining():
        return request.options.time_limit_seconds - (time.perf_counter() - started)

    has_stability = bool(context.previous_assignments)
    stage_names = [priority.value for priority in PRIORITY_ORDER] + [FAIRNESS_STAGE]
    if has_stability:
        stage_names.append(STABILITY_STAGE)

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
            stability=None,
            elapsed_seconds=time.perf_counter() - started,
        )

    task_type_by_id = {task_type.id: task_type for task_type in request.task_types}

    # Committed work must be executable: its fixed employee must still be
    # eligible. In-progress work is grandfathered: skills may have changed
    # since it started, but the employee is validated at the request boundary.
    committed_duration: dict[str, int] = {}
    fixed_intervals: dict[str, list[tuple[int, int, str]]] = {
        employee.id: [] for employee in request.employees
    }
    fixed_load: dict[str, int] = {employee.id: 0 for employee in request.employees}
    fixed_finish_by_priority: dict[str, int] = {priority.value: 0 for priority in PRIORITY_ORDER}
    for record in context.in_progress:
        task = task_by_id[record.task_id]
        fixed_intervals[record.employee_id].append(
            (current_time, current_time + record.remaining_minutes, f"in-progress task {record.task_id!r}")
        )
        fixed_load[record.employee_id] += record.remaining_minutes
        fixed_finish_by_priority[task.priority.value] += current_time + record.remaining_minutes
    for record in context.committed:
        task = task_by_id[record.task_id]
        employee = employee_by_id[record.employee_id]
        task_type = task_type_by_id[task.task_type_id]
        missing = task_type.required_skills - employee.skills
        if missing:
            raise ValueError(
                f"committed task {record.task_id!r} requires skills employee {record.employee_id!r} lacks: {sorted(missing)}"
            )
        duration = task_type.base_duration * AFFINITY_MULTIPLIER[_employee_affinity(employee, task)]
        committed_duration[record.task_id] = duration
        fixed_intervals[record.employee_id].append(
            (record.start, record.start + duration, f"committed task {record.task_id!r}")
        )
        fixed_load[record.employee_id] += duration
        fixed_finish_by_priority[task.priority.value] += record.start + duration
    for employee_id, intervals in fixed_intervals.items():
        ordered = sorted(intervals)
        for before, after in zip(ordered, ordered[1:]):
            if after[0] < before[1]:
                raise ValueError(
                    f"fixed intervals overlap for employee {employee_id!r}: "
                    f"{before[2]} [{before[0]},{before[1]}) and {after[2]} [{after[0]},{after[1]})"
                )

    eligible: dict[str, list[Employee]] = {}
    duration_of: dict[tuple[str, str], int] = {}
    for task in pending:
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
        for task in pending
        if eligible[task.id]
    ]
    max_release = max(
        (max(task.earliest_start, current_time) for task in pending if eligible[task.id]),
        default=0,
    )
    fixed_finishes = [
        current_time + record.remaining_minutes for record in context.in_progress
    ] + [
        record.start + committed_duration[record.task_id] for record in context.committed
    ]
    horizon = max([current_time, max_release, *fixed_finishes]) + sum(max_durations)

    load_bound = len(request.employees) * horizon**2
    completion_bound = max(
        (sum(1 for task in pending if eligible[task.id] and task.priority == priority)
         for priority in PRIORITY_ORDER),
        default=0,
    ) * horizon
    if horizon**2 > _CP_SAT_MAX_INT // 2 or load_bound > _CP_SAT_MAX_INT // 2 or completion_bound > _CP_SAT_MAX_INT // 2:
        raise ValueError("planning horizon and stage objective domains exceed CP-SAT integer limits")

    unassigned_pre: list[UnassignedTask] = []
    for task in pending:
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
    squared_loads: list[cp_model.IntVar] = []
    load_terms: dict[str, list] = {employee.id: [] for employee in request.employees}

    for task in pending:
        if not eligible[task.id]:
            continue
        release = max(task.earliest_start, current_time)
        finish = model.NewIntVar(release, horizon, f"finish_{task.id}")
        task_finish[task.id] = finish
        for employee in eligible[task.id]:
            duration = duration_of[(task.id, employee.id)]
            suffix = f"{task.id}_{employee.id}"
            presence = model.NewBoolVar(f"present_{suffix}")
            start = model.NewIntVar(release, horizon, f"start_{suffix}")
            pair_finish = model.NewIntVar(release + duration, horizon, f"pf_{suffix}")
            interval = model.NewOptionalIntervalVar(
                start, duration, pair_finish, presence, f"interval_{suffix}"
            )
            model.Add(finish == pair_finish).OnlyEnforceIf(presence)
            load_terms[employee.id].append(duration * presence)
            employee_intervals.setdefault(employee.id, []).append(interval)
            presence_of.setdefault(task.id, []).append((employee, presence))
            start_of[(task.id, employee.id)] = start
        model.AddExactlyOne([presence for _, presence in presence_of[task.id]])

    # In-progress tasks occupy the employee from now until their remaining
    # work is done; committed tasks occupy the fixed future interval. Neither
    # is rescheduled and neither is reconsidered for employee or timing.
    for record in context.in_progress:
        interval = model.NewIntervalVar(
            current_time,
            record.remaining_minutes,
            current_time + record.remaining_minutes,
            f"fixed_in_progress_{record.task_id}",
        )
        employee_intervals.setdefault(record.employee_id, []).append(interval)
    for record in context.committed:
        duration = committed_duration[record.task_id]
        interval = model.NewIntervalVar(
            record.start, duration, record.start + duration, f"fixed_committed_{record.task_id}"
        )
        employee_intervals.setdefault(record.employee_id, []).append(interval)

    for employee in request.employees:
        model.AddNoOverlap(employee_intervals.get(employee.id, []))
        load = model.NewIntVar(0, horizon, f"load_{employee.id}")
        model.Add(load == sum(load_terms[employee.id]) + fixed_load[employee.id])
        squared = model.NewIntVar(0, horizon * horizon, f"squared_load_{employee.id}")
        model.AddMultiplicationEquality(squared, [load, load])
        squared_loads.append(squared)

    stage_vars: list[tuple[str, cp_model.IntVar | None]] = []
    for priority in PRIORITY_ORDER:
        tasks_p = [
            task for task in pending
            if eligible[task.id] and task.priority == priority
        ]
        fixed_count = sum(
            1 for task in request.tasks
            if task.priority == priority
            and (task.id in in_progress_by_task or task.id in committed_by_task)
        )
        if not tasks_p and not fixed_count:
            stage_vars.append((priority.value, None))
            continue
        total = model.NewIntVar(0, (len(tasks_p) + fixed_count) * horizon, f"total_{priority.value}")
        model.Add(
            total == sum(task_finish[task.id] for task in tasks_p) + fixed_finish_by_priority[priority.value]
        )
        stage_vars.append((priority.value, total))

    fairness_objective = sum(squared_loads) if squared_loads else None
    stage_vars.append((FAIRNESS_STAGE, fairness_objective))

    stability_objective: cp_model.IntVar | None = None
    if has_stability:
        unchanged_vars: list[cp_model.IntVar] = []
        for previous in context.previous_assignments:
            if (
                previous.task_id in completed_ids
                or previous.task_id in in_progress_by_task
                or previous.task_id in committed_by_task
            ):
                continue
            unchanged = model.NewBoolVar(f"unchanged_{previous.task_id}")
            presence_map = {
                employee.id: presence
                for employee, presence in presence_of.get(previous.task_id, [])
            }
            if previous.employee_id not in presence_map:
                model.Add(unchanged == 0)
            else:
                presence = presence_map[previous.employee_id]
                start_var = start_of[(previous.task_id, previous.employee_id)]
                same_start = model.NewBoolVar(f"same_start_{previous.task_id}")
                model.Add(start_var == previous.start).OnlyEnforceIf(same_start)
                model.Add(start_var != previous.start).OnlyEnforceIf(same_start.Not())
                model.AddBoolAnd([presence, same_start]).OnlyEnforceIf(unchanged)
                model.AddBoolOr([presence.Not(), same_start.Not()]).OnlyEnforceIf(unchanged.Not())
            unchanged_vars.append(unchanged)
        if unchanged_vars:
            stability_objective = model.NewIntVar(0, len(unchanged_vars), "stability_changed")
            model.Add(stability_objective == len(unchanged_vars) - sum(unchanged_vars))
    if has_stability:
        stage_vars.append((STABILITY_STAGE, stability_objective))

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
        for task in pending:
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
        for record in context.in_progress:
            scheduled_by_employee[record.employee_id].append(
                TaskAssignment(
                    task_id=record.task_id,
                    start=record.actual_start,
                    finish=current_time + record.remaining_minutes,
                    duration=record.remaining_minutes,
                    actual_start=record.actual_start,
                    in_progress=True,
                )
            )
        for record in context.committed:
            duration = committed_duration[record.task_id]
            scheduled_by_employee[record.employee_id].append(
                TaskAssignment(
                    task_id=record.task_id,
                    start=record.start,
                    finish=record.start + duration,
                    duration=duration,
                )
            )
        for employee in request.employees:
            tasks = sorted(scheduled_by_employee[employee.id], key=lambda item: item.start)
            if tasks:
                makespan = max(makespan, tasks[-1].finish)
            employee_schedules.append(EmployeeSchedule(employee_id=employee.id, tasks=tasks))
        return employee_schedules, makespan

    def stability_metrics(schedules: list[EmployeeSchedule]) -> StabilityMetrics:
        assigned = {
            item.task_id: (schedule.employee_id, item.start)
            for schedule in schedules for item in schedule.tasks
        }
        changes: list[ReplanningChange] = []
        tracked = 0
        for previous in context.previous_assignments:
            if (
                previous.task_id in completed_ids
                or previous.task_id in in_progress_by_task
                or previous.task_id in committed_by_task
            ):
                continue
            tracked += 1
            new = assigned.get(previous.task_id)
            if new is None:
                changes.append(
                    ReplanningChange(
                        task_id=previous.task_id,
                        previous_employee_id=previous.employee_id,
                        previous_start=previous.start,
                    )
                )
            elif new != (previous.employee_id, previous.start):
                changes.append(
                    ReplanningChange(
                        task_id=previous.task_id,
                        previous_employee_id=previous.employee_id,
                        previous_start=previous.start,
                        new_employee_id=new[0],
                        new_start=new[1],
                    )
                )
        return StabilityMetrics(
            changed_tasks=len(changes),
            unchanged_tasks=tracked - len(changes),
            changes=changes,
        )

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0

    for name, stage_objective in stage_vars:
        if stage_objective is None:
            records.append(StageRecord(name=name, status="OPTIMAL", proven=True, value=0, bound=0))
            if name in {priority.value for priority in PRIORITY_ORDER}:
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
            # Lock every proven stage, fairness included, so a later stage
            # (stability) cannot trade away an earlier optimum.
            model.Add(stage_objective == value)
            if name in {priority.value for priority in PRIORITY_ORDER}:
                proven_priorities.append(name)
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
                stability=stability_metrics([]) if has_stability else None,
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
        stability=stability_metrics(schedules) if has_stability else None,
        elapsed_seconds=time.perf_counter() - started,
    )
