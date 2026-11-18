
from task_orchestration import Customer, Employee, Task, TaskType, solve

from helpers import brute_force_optimum, make_request, result_lexicographic


def test_oracle_matches_balanced_two_employees():
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
        ],
    )
    result = solve(request)
    assert result.status == "OPTIMAL"
    assert not result.provisional
    assert result_lexicographic(result) == brute_force_optimum(request)


def test_oracle_matches_affinity_and_priorities():
    request = make_request(
        employees=[
            Employee(id="e1", name="Ann", skills={"a"}, customer_affinities={"c1": "HIGH"}),
            Employee(id="e2", name="Bob", skills={"a"}, customer_affinities={"c1": "MEDIUM"}),
        ],
        customers=[Customer(id="c1", name="Alpha")],
        task_types=[
            TaskType(id="tt_short", base_duration=5, required_skills={"a"}),
            TaskType(id="tt_long", base_duration=15, required_skills={"a"}),
        ],
        tasks=[
            Task(id="t1", task_type_id="tt_short", customer_id="c1", earliest_start=0, priority="CRITICAL"),
            Task(id="t2", task_type_id="tt_long", customer_id="c1", earliest_start=0, priority="LOW"),
            Task(id="t3", task_type_id="tt_short", customer_id="c1", earliest_start=5, priority="MEDIUM"),
        ],
    )
    result = solve(request)
    assert result.status == "OPTIMAL"
    assert result_lexicographic(result) == brute_force_optimum(request)


def test_oracle_matches_release_times_and_idle():
    request = make_request(
        employees=[
            Employee(id="e1", name="Ann", skills={"a"}),
            Employee(id="e2", name="Bob", skills={"a"}),
        ],
        customers=[Customer(id="c1", name="Alpha")],
        task_types=[TaskType(id="tt", base_duration=10, required_skills={"a"})],
        tasks=[
            Task(id="t1", task_type_id="tt", customer_id="c1", earliest_start=0, priority="LOW"),
            Task(id="t2", task_type_id="tt", customer_id="c1", earliest_start=25, priority="HIGH"),
            Task(id="t3", task_type_id="tt", customer_id="c1", earliest_start=30, priority="LOW"),
        ],
    )
    result = solve(request)
    assert result.status == "OPTIMAL"
    assert result_lexicographic(result) == brute_force_optimum(request)


def test_oracle_matches_larger_two_employee_case():
    request = make_request(
        employees=[
            Employee(id="e1", name="Ann", skills={"a", "b"}, customer_affinities={"c1": "LOW"}),
            Employee(id="e2", name="Bob", skills={"a"}, customer_affinities={"c1": "HIGH"}),
        ],
        customers=[Customer(id="c1", name="Alpha")],
        task_types=[
            TaskType(id="tt_a", base_duration=10, required_skills={"a"}),
            TaskType(id="tt_b", base_duration=20, required_skills={"b"}),
        ],
        tasks=[
            Task(id="t1", task_type_id="tt_a", customer_id="c1", earliest_start=0, priority="CRITICAL"),
            Task(id="t2", task_type_id="tt_a", customer_id="c1", earliest_start=0, priority="LOW"),
            Task(id="t3", task_type_id="tt_b", customer_id="c1", earliest_start=5, priority="HIGH"),
            Task(id="t4", task_type_id="tt_a", customer_id="c1", earliest_start=15, priority="LOW"),
        ],
    )
    result = solve(request)
    assert result.status == "OPTIMAL"
    assert result_lexicographic(result) == brute_force_optimum(request)


def test_lower_priority_cannot_worsen_higher_aggregate():
    request = make_request(
        employees=[Employee(id="e1", name="Ann", skills={"a"})],
        customers=[Customer(id="c1", name="Alpha")],
        task_types=[TaskType(id="tt", base_duration=5, required_skills={"a"})],
        tasks=[
            Task(id="critical", task_type_id="tt", customer_id="c1", earliest_start=0, priority="CRITICAL"),
            Task(id="medium", task_type_id="tt", customer_id="c1", earliest_start=0, priority="MEDIUM"),
            Task(id="low", task_type_id="tt", customer_id="c1", earliest_start=0, priority="LOW"),
        ],
    )
    result = solve(request)
    assert result.status == "OPTIMAL"
    totals = result.objective.priority_completion_totals
    starts = {item.task_id: item.start for schedule in result.assignments for item in schedule.tasks}
    # Putting the low task first would lower its total but delay every
    # higher priority task; strict lexicographic order forbids that.
    assert starts["critical"] < starts["medium"] < starts["low"]
    assert totals["CRITICAL"] == 20
    assert totals["MEDIUM"] == 40
    assert totals["LOW"] == 60
    assert result_lexicographic(result) == brute_force_optimum(request)


def test_permutations_allowed_at_fixed_total():
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
        ],
    )
    result = solve(request)
    assert result.status == "OPTIMAL"
    # Any split keeps completion totals at 40+40; fairness then balances loads.
    totals = result.objective.priority_completion_totals
    assert totals["LOW"] == 80
    loads = result.objective.employee_work_minutes
    assert sorted(loads.values()) == [40, 40]
    assert result.objective.squared_load_cost == 3200
