
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
            Task(id="t1", task_type_id="weld_type", customer_id="c1", earliest_start=5, priority="HIGH"),
            Task(id="t2", task_type_id="drill_type", customer_id="c1", earliest_start=0, priority="LOW"),
            Task(id="t3", task_type_id="weld_type", customer_id="c1", earliest_start=0, priority="CRITICAL"),
        ],
    )
    result = solve(request)
    assert result.status == "OPTIMAL"
    assert not result.provisional
    assert result.proven_priorities == ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
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
        tasks=[Task(id="t1", task_type_id="tt", customer_id="c1", earliest_start=0, priority="LOW")],
    )
    result = solve(request)
    assert result.status == "OPTIMAL"
    assert not result.provisional
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
    assert not result.provisional
    assert result.proven_priorities == ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
    assert result.unassigned == []
    assert result.makespan == 0
    assert all(total == 0 for total in result.objective.priority_completion_totals.values())
    assert result.objective.squared_load_cost == 0


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
            Task(id="t2", task_type_id="tt", customer_id="c1", earliest_start=0, priority="LOW"),
            Task(id="t3", task_type_id="tt", customer_id="c1", earliest_start=0, priority="MEDIUM"),
        ],
    )
    result = solve(request)
    assert result.status == "OPTIMAL"
    expected_totals = {priority: 0 for priority in ("CRITICAL", "HIGH", "MEDIUM", "LOW")}
    priority_by_task = {"t1": "CRITICAL", "t2": "LOW", "t3": "MEDIUM"}
    expected_loads = {schedule.employee_id: 0 for schedule in result.assignments}
    for schedule in result.assignments:
        for item in schedule.tasks:
            expected_totals[priority_by_task[item.task_id]] += item.finish
            expected_loads[schedule.employee_id] += item.duration
    assert result.objective.priority_completion_totals == expected_totals
    assert result.objective.employee_work_minutes == expected_loads
    assert result.objective.squared_load_cost == sum(load**2 for load in expected_loads.values())
    makespan_expected = max(
        (item.finish for _, item in scheduled_tasks(result)), default=0
    )
    assert result.makespan == makespan_expected


def test_optimality_information_present():
    request = make_request(
        employees=[Employee(id="e1", name="Ann", skills={"a"})],
        customers=[Customer(id="c1", name="Alpha")],
        task_types=[TaskType(id="tt", base_duration=5, required_skills={"a"})],
        tasks=[Task(id="t1", task_type_id="tt", customer_id="c1", earliest_start=0, priority="LOW")],
    )
    result = solve(request)
    assert result.status == "OPTIMAL"
    assert not result.provisional
    for record in result.stages:
        assert record.proven
        assert record.bound is not None and record.value is not None
        assert record.bound <= record.value
    low_stage = next(record for record in result.stages if record.name == "LOW")
    assert low_stage.value == 20 and low_stage.bound == 20
    assert result.elapsed_seconds >= 0


def test_affinity_changes_assigned_work_minutes():
    request = make_request(
        employees=[
            Employee(id="expert", name="Ann", skills={"a"}, customer_affinities={"c1": "HIGH"}),
            Employee(id="novice", name="Bob", skills={"a"}),
        ],
        customers=[Customer(id="c1", name="Alpha")],
        task_types=[TaskType(id="tt", base_duration=10, required_skills={"a"})],
        tasks=[
            Task(id="t1", task_type_id="tt", customer_id="c1", earliest_start=0, priority="LOW"),
        ],
    )
    result = solve(request)
    assert result.status == "OPTIMAL"
    # HIGH affinity duration is 10 and NONE is 40; the LOW completion total
    # is minimized by giving the task to the expert.
    assert result.objective.employee_work_minutes == {"expert": 10, "novice": 0}
    assert result.objective.squared_load_cost == 100
    durations = {item.task_id: item.duration for schedule in result.assignments for item in schedule.tasks}
    assert durations["t1"] == 10
    assert result.makespan == 10


def test_fairness_chooses_balanced_work_minutes():
    request = make_request(
        employees=[
            Employee(id="e1", name="Ann", skills={"a"}),
            Employee(id="e2", name="Bob", skills={"a"}),
        ],
        customers=[Customer(id="c1", name="Alpha")],
        task_types=[TaskType(id="tt", base_duration=10, required_skills={"a"})],
        tasks=[
            Task(id="t1", task_type_id="tt", customer_id="c1", earliest_start=0, priority="LOW"),
            Task(id="t2", task_type_id="tt", customer_id="c1", earliest_start=0, priority="LOW"),
            Task(id="t3", task_type_id="tt", customer_id="c1", earliest_start=0, priority="LOW"),
        ],
    )
    result = solve(request)
    assert result.status == "OPTIMAL"
    # Completion totals are fixed once the LOW stage locks the split at
    # 80/40 work minutes; that split minimizes the squared load 6400+1600.
    assert result.objective.squared_load_cost == 8000
    assert sorted(result.objective.employee_work_minutes.values()) == [40, 80]


def test_legacy_priority_aliases_normalize():
    request = make_request(
        employees=[Employee(id="e1", name="Ann", skills={"a"})],
        customers=[Customer(id="c1", name="Alpha")],
        task_types=[TaskType(id="tt", base_duration=5, required_skills={"a"})],
        tasks=[
            Task(id="major", task_type_id="tt", customer_id="c1", earliest_start=0, priority="MAJOR"),
            Task(id="minor", task_type_id="tt", customer_id="c1", earliest_start=0, priority="MINOR"),
        ],
    )
    assert request.tasks[0].priority == "HIGH"
    assert request.tasks[1].priority == "LOW"
    result = solve(request)
    assert result.status == "OPTIMAL"
    assert result.proven_priorities == ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
    # MAJOR is treated as HIGH: its stage is minimized before the minor task.
    starts = {item.task_id: item.start for schedule in result.assignments for item in schedule.tasks}
    assert starts["major"] < starts["minor"]
