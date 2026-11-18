"""End-to-end replanning example.

Solve a first plan, then time advances: one task finished, one is running,
and an urgent job arrives. A second solve keeps the running work in place,
reserves its employee for the remaining minutes, and replans everything else
from the new current time while holding the strict priority policy.
"""

from task_orchestration import (
    Customer,
    Employee,
    InProgressRecord,
    PlanningRequest,
    PreviousAssignmentRecord,
    ReplanningContext,
    SolveOptions,
    Task,
    TaskType,
    solve,
)

employees = [
    Employee(id="e1", name="Ann", skills={"weld"}, customer_affinities={"c1": "HIGH"}),
    Employee(id="e2", name="Bob", skills={"weld"}, customer_affinities={"c1": "HIGH"}),
]
customers = [Customer(id="c1", name="Alpha Co")]
task_types = [TaskType(id="weld_type", base_duration=30, required_skills={"weld"}, customer_affinities={"c1": "HIGH"})]

first_request = PlanningRequest(
    employees=employees,
    customers=customers,
    task_types=task_types,
    tasks=[
        Task(id="job1", task_type_id="weld_type", customer_id="c1", earliest_start=0, priority="HIGH"),
        Task(id="job2", task_type_id="weld_type", customer_id="c1", earliest_start=0, priority="MEDIUM"),
        Task(id="job3", task_type_id="weld_type", customer_id="c1", earliest_start=0, priority="LOW"),
    ],
    options=SolveOptions(time_limit_seconds=5.0),
)

first_result = solve(first_request)
print("first solve:", first_result.status)
for schedule in first_result.assignments:
    print(" ", schedule.employee_id, [(t.task_id, t.start, t.finish) for t in schedule.tasks])

# 40 minutes pass: job1 is done, job2 started on Ann and has 20 minutes left,
# and an urgent CRITICAL job just arrived.
second_request = PlanningRequest(
    employees=employees,
    customers=customers,
    task_types=task_types,
    tasks=[
        Task(id="job1", task_type_id="weld_type", customer_id="c1", earliest_start=0, priority="HIGH"),
        Task(id="job2", task_type_id="weld_type", customer_id="c1", earliest_start=0, priority="MEDIUM"),
        Task(id="job3", task_type_id="weld_type", customer_id="c1", earliest_start=0, priority="LOW"),
        Task(id="urgent", task_type_id="weld_type", customer_id="c1", earliest_start=0, priority="CRITICAL"),
    ],
    replanning=ReplanningContext(
        current_time=40,
        completed_task_ids=["job1"],
        in_progress=[
            InProgressRecord(task_id="job2", employee_id="e1", actual_start=30, remaining_minutes=20)
        ],
        previous_assignments=[
            PreviousAssignmentRecord(task_id=a.task_id, employee_id=schedule.employee_id, start=a.start)
            for schedule in first_result.assignments
            for a in schedule.tasks
        ],
    ),
    options=SolveOptions(time_limit_seconds=5.0),
)

second_result = solve(second_request)
print("second solve:", second_result.status)
for schedule in second_result.assignments:
    print(" ", schedule.employee_id, [(t.task_id, t.start, t.finish) for t in schedule.tasks])
print("stability:", second_result.stability)
