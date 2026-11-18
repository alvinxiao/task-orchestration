
from task_orchestration import Customer, Employee, Task, TaskType, solve

from helpers import make_request


def scheduled_tasks(result):
    for schedule in result.assignments:
        for item in schedule.tasks:
            yield schedule.employee_id, item


def test_assignments_respect_skills_release_and_no_overlap():
    request = make_request(
        employees=[
            Employee(id="e1", name="Ann", skills={"weld"}),
            Employee(id="e2", name="Bob", skills={"drill"}),
        ],
        customers=[Customer(id="c1", name="Alpha")],
        task_types=[
            TaskType(id="weld_type", base_duration=30, required_skills={"weld"}),
            TaskType(id="drill_type", base_duration=45, required_skills={"drill"}),
        ],
        tasks=[
            Task(id="t1", task_type_id="weld_type", customer_id="c1", earliest_start=5, priority="MAJOR"),
            Task(id="t2", task_type_id="drill_type", customer_id="c1", earliest_start=0, priority="MINOR"),
            Task(id="t3", task_type_id="weld_type", customer_id="c1", earliest_start=0, priority="CRITICAL"),
        ],
    )
    result = solve(request)
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert not result.unassigned
    task_type_durations = {"t1": 120, "t2": 180, "t3": 120}
    skills = {"t1": {"weld"}, "t2": {"drill"}, "t3": {"weld"}}
    releases = {"t1": 5, "t2": 0, "t3": 0}
    seen = {}
    per_employee = {}
    for employee_id, item in scheduled_tasks(result):
        assert item.task_id not in seen
        seen[item.task_id] = (employee_id, item)
        per_employee.setdefault(employee_id, []).append(item)
    assert set(seen) == {task.id for task in request.tasks}
    for task_id, (employee_id, item) in seen.items():
        employee = next(e for e in request.employees if e.id == employee_id)
        task_type = next(t for t in request.task_types if t.id == next(x for x in request.tasks if x.id == task_id).task_type_id)
        assert task_type.required_skills <= employee.skills
        assert item.start >= releases[task_id]
        assert item.duration == task_type_durations[task_id]
        assert item.finish == item.start + item.duration
    for items in per_employee.values():
        ordered = sorted(items, key=lambda x: x.start)
        for before, after in zip(ordered, ordered[1:]):
            assert before.finish <= after.start


def test_unassignable_task_reported():
    request = make_request(
        employees=[Employee(id="e1", name="Ann", skills={"weld"})],
        customers=[Customer(id="c1", name="Alpha")],
        task_types=[TaskType(id="solder", base_duration=15, required_skills={"solder"})],
        tasks=[Task(id="t1", task_type_id="solder", customer_id="c1", earliest_start=0, priority="CRITICAL")],
    )
    result = solve(request)
    assert result.status == "OPTIMAL"
    assert [item.task_id for item in result.unassigned] == ["t1"]
    assert "solder" in result.unassigned[0].reason
    assert all(not schedule.tasks for schedule in result.assignments)


def test_no_employees_all_tasks_unassigned():
    request = make_request(
        employees=[],
        customers=[Customer(id="c1", name="Alpha")],
        task_types=[TaskType(id="tt", base_duration=10, required_skills=set())],
        tasks=[Task(id="t1", task_type_id="tt", customer_id="c1", earliest_start=0, priority="MINOR")],
    )
    result = solve(request)
    assert result.status == "OPTIMAL"
    assert [item.task_id for item in result.unassigned] == ["t1"]
    assert result.makespan == 0


def test_no_tasks_is_valid():
    request = make_request(
        employees=[Employee(id="e1", name="Ann", skills=set())],
        customers=[Customer(id="c1", name="Alpha")],
        task_types=[],
        tasks=[],
    )
    result = solve(request)
    assert result.status == "OPTIMAL"
    assert result.unassigned == []
    assert result.makespan == 0
    assert result.objective.squared_employee_finish_cost == 0
    assert result.objective.weighted_task_completion_cost == 0


def test_reported_metrics_match_returned_schedule():
    request = make_request(
        employees=[
            Employee(id="e1", name="Ann", skills={"a"}, customer_affinities={"c1": "HIGH"}),
            Employee(id="e2", name="Bob", skills={"a"}),
        ],
        customers=[Customer(id="c1", name="Alpha")],
        task_types=[TaskType(id="tt", base_duration=10, required_skills={"a"})],
        tasks=[
            Task(id="t1", task_type_id="tt", customer_id="c1", earliest_start=0, priority="CRITICAL"),
            Task(id="t2", task_type_id="tt", customer_id="c1", earliest_start=0, priority="MINOR"),
            Task(id="t3", task_type_id="tt", customer_id="c1", earliest_start=0, priority="MAJOR"),
        ],
    )
    result = solve(request)
    assert result.status == "OPTIMAL"
    squared = 0
    weighted_weights = {"t1": 4, "t2": 1, "t3": 2}
    for schedule in result.assignments:
        last_finish = 0
        for item in schedule.tasks:
            last_finish = item.finish
        squared += last_finish**2
    assert result.objective.squared_employee_finish_cost == squared
    makespan_expected = max(
        (item.finish for _, item in scheduled_tasks(result)), default=0
    )
    assert result.makespan == makespan_expected
    weighted_expected = sum(
        weighted_weights[item.task_id] * item.finish for _, item in scheduled_tasks(result)
    )
    assert result.objective.weighted_task_completion_cost == weighted_expected


def test_optimality_information_present():
    request = make_request(
        employees=[Employee(id="e1", name="Ann", skills={"a"})],
        customers=[Customer(id="c1", name="Alpha")],
        task_types=[TaskType(id="tt", base_duration=5, required_skills={"a"})],
        tasks=[Task(id="t1", task_type_id="tt", customer_id="c1", earliest_start=0, priority="MINOR")],
    )
    result = solve(request)
    assert result.status == "OPTIMAL"
    assert result.best_bound is not None
    assert result.best_bound <= result.objective.squared_employee_finish_cost + result.objective.weighted_task_completion_cost
    assert result.elapsed_seconds >= 0
