
from __future__ import annotations

import itertools

from task_orchestration import (
    Customer,
    Employee,
    PlanningRequest,
    ReplanningContext,
    SolveOptions,
    Task,
    TaskType,
)


AFFINITY_MULTIPLIER = {"NONE": 4, "LOW": 3, "MEDIUM": 2, "HIGH": 1}
PRIORITY_ORDER = ("CRITICAL", "HIGH", "MEDIUM", "LOW")

def make_request(employees, customers, task_types, tasks, time_limit=10.0, replanning=None):
    return PlanningRequest(
        employees=employees,
        customers=customers,
        task_types=task_types,
        tasks=tasks,
        replanning=replanning if replanning is not None else ReplanningContext(),
        options=SolveOptions(time_limit_seconds=time_limit),
    )


def lexicographic_tuple(totals_by_priority, squared_load_cost):
    """Independent lexicographic objective: per-priority completion totals
    in strict order CRITICAL, HIGH, MEDIUM, LOW, then squared load cost."""
    return tuple(totals_by_priority[priority] for priority in PRIORITY_ORDER) + (squared_load_cost,)


def evaluate(schedule_by_employee, durations):
    """Return (per-priority completion totals, squared load cost) for one
    candidate assignment and ordering, left-shifted per employee."""
    totals = {priority: 0 for priority in PRIORITY_ORDER}
    squared = 0
    for tasks in schedule_by_employee.values():
        now = 0
        load = 0
        for task in tasks:
            start = max(now, task.earliest_start)
            now = start + durations[task.id]
            load += durations[task.id]
            totals[task.priority] += now
        squared += load**2
    return totals, squared


def brute_force_optimum(request):
    """Minimum lexicographic tuple over every assignment and ordering."""
    task_types = {task_type.id: task_type for task_type in request.task_types}
    durations = {}
    eligible: dict[str, list[str]] = {}
    for task in request.tasks:
        required = task_types[task.task_type_id].required_skills
        candidates = [employee.id for employee in request.employees if required <= employee.skills]
        if not candidates:
            return None
        eligible[task.id] = candidates
        for employee in request.employees:
            if employee.id in candidates:
                multiplier = employee.customer_affinities.get(task.customer_id, "NONE")
                durations[(task.id, employee.id)] = (
                    task_types[task.task_type_id].base_duration * AFFINITY_MULTIPLIER[multiplier]
                )

    employee_ids = [employee.id for employee in request.employees]
    best = None
    assignment_sets = itertools.product(*[eligible[task.id] for task in request.tasks])
    for assignment in assignment_sets:
        by_employee: dict[str, list[Task]] = {employee_id: [] for employee_id in employee_ids}
        for task, employee_id in zip(request.tasks, assignment):
            by_employee[employee_id].append(task)
        orderings = [list(itertools.permutations(by_employee[employee_id])) for employee_id in employee_ids]
        for combination in itertools.product(*orderings):
            schedule = {employee_id: list(order) for employee_id, order in zip(by_employee, combination)}
            candidate_durations = {
                task.id: durations[(task.id, employee_id)]
                for employee_id, group in schedule.items()
                for task in group
            }
            totals, squared = evaluate(schedule, candidate_durations)
            candidate = lexicographic_tuple(totals, squared)
            if best is None or candidate < best:
                best = candidate
    return best


def result_lexicographic(result):
    totals = result.objective.priority_completion_totals
    return lexicographic_tuple(totals, result.objective.squared_load_cost)
