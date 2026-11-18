
from __future__ import annotations

import itertools

from task_orchestration import (
    Customer,
    Employee,
    PlanningRequest,
    SolveOptions,
    Task,
    TaskType,
)


AFFINITY_MULTIPLIER = {"NONE": 4, "LOW": 3, "MEDIUM": 2, "HIGH": 1}
PRIORITY_WEIGHT = {"CRITICAL": 4, "MAJOR": 2, "MINOR": 1}

def make_request(employees, customers, task_types, tasks, time_limit=10.0):
    return PlanningRequest(
        employees=employees,
        customers=customers,
        task_types=task_types,
        tasks=tasks,
        options=SolveOptions(time_limit_seconds=time_limit),
    )


def evaluate(schedule_by_employee, durations):
    squared = 0
    weighted = 0
    for tasks in schedule_by_employee.values():
        now = 0
        last_finish = 0
        for task in tasks:
            start = max(now, task.earliest_start)
            now = start + durations[task.id]
            last_finish = now
            weighted += PRIORITY_WEIGHT[task.priority] * now
        squared += last_finish**2
    return squared, weighted


def brute_force_optimum(request):
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
            squared, weighted = evaluate(schedule, candidate_durations)
            total = squared + weighted
            if best is None or total < best:
                best = total
    return best
