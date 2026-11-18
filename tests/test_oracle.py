
from task_orchestration import Customer, Employee, Task, TaskType, solve

from helpers import brute_force_optimum, make_request


def result_objective(result):
    return result.objective.squared_employee_finish_cost + result.objective.weighted_task_completion_cost


def test_oracle_matches_balanced_two_employees():
    request = make_request(
        employees=[
            Employee(id="e1", name="Ann", skills={"a"}),
            Employee(id="e2", name="Bob", skills={"a"}),
        ],
        customers=[Customer(id="c1", name="Alpha")],
        task_types=[TaskType(id="tt", base_duration=10, required_skills={"a"})],
        tasks=[
            Task(id="t1", task_type_id="tt", customer_id="c1", earliest_start=0, priority="MINOR"),
            Task(id="t2", task_type_id="tt", customer_id="c1", earliest_start=0, priority="MINOR"),
        ],
    )
    result = solve(request)
    assert result.status == "OPTIMAL"
    assert result_objective(result) == brute_force_optimum(request)


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
            Task(id="t2", task_type_id="tt_long", customer_id="c1", earliest_start=0, priority="MINOR"),
            Task(id="t3", task_type_id="tt_short", customer_id="c1", earliest_start=5, priority="MAJOR"),
        ],
    )
    result = solve(request)
    assert result.status == "OPTIMAL"
    assert result_objective(result) == brute_force_optimum(request)


def test_weighted_completion_beats_makespan_tie():
    request = make_request(
        employees=[Employee(id="e1", name="Ann", skills={"a"}, customer_affinities={"c1": "HIGH"})],
        customers=[Customer(id="c1", name="Alpha")],
        task_types=[TaskType(id="tt", base_duration=10, required_skills={"a"})],
        tasks=[
            Task(id="minor", task_type_id="tt", customer_id="c1", earliest_start=0, priority="MINOR"),
            Task(id="critical", task_type_id="tt", customer_id="c1", earliest_start=0, priority="CRITICAL"),
        ],
    )
    result = solve(request)
    assert result.status == "OPTIMAL"
    weights = {"minor": 1, "critical": 4}
    tasks = {item.task_id: item for item in result.assignments[0].tasks}
    assert result.makespan == 20
    assert result.objective.squared_employee_finish_cost == 400
    assert result.objective.weighted_task_completion_cost == sum(
        weights[task_id] * item.finish for task_id, item in tasks.items()
    ) == 60
    assert brute_force_optimum(request) == 460


def test_squared_objective_can_choose_larger_makespan():
    request = make_request(
        employees=[
            Employee(id="fast", name="Fast", skills={"special"}, customer_affinities={"c": "HIGH"}),
            Employee(id="slow", name="Slow"),
        ],
        customers=[Customer(id="c", name="Customer")],
        task_types=[TaskType(id="fixed", base_duration=100, required_skills={"special"}),
                    TaskType(id="flex", base_duration=20)],
        tasks=[Task(id="fixed", task_type_id="fixed", customer_id="c", earliest_start=0, priority="MINOR"),
               Task(id="flex", task_type_id="flex", customer_id="c", earliest_start=0, priority="MINOR")],
    )
    result = solve(request)
    assert result.status == "OPTIMAL"
    assert result.makespan == 120
    assert result.objective.squared_employee_finish_cost == 14_400
    assert result_objective(result) == brute_force_optimum(request) == 14_540
    # Splitting the tasks finishes at 100 and 80, with cost 16,580.
    assert result_objective(result) < 100**2 + 80**2 + 100 + 80


def test_oracle_matches_release_times_and_idle():
    request = make_request(
        employees=[
            Employee(id="e1", name="Ann", skills={"a"}),
            Employee(id="e2", name="Bob", skills={"a"}),
        ],
        customers=[Customer(id="c1", name="Alpha")],
        task_types=[TaskType(id="tt", base_duration=10, required_skills={"a"})],
        tasks=[
            Task(id="t1", task_type_id="tt", customer_id="c1", earliest_start=0, priority="MINOR"),
            Task(id="t2", task_type_id="tt", customer_id="c1", earliest_start=25, priority="MAJOR"),
            Task(id="t3", task_type_id="tt", customer_id="c1", earliest_start=30, priority="MINOR"),
        ],
    )
    result = solve(request)
    assert result.status == "OPTIMAL"
    assert result_objective(result) == brute_force_optimum(request)


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
            Task(id="t2", task_type_id="tt_a", customer_id="c1", earliest_start=0, priority="MINOR"),
            Task(id="t3", task_type_id="tt_b", customer_id="c1", earliest_start=5, priority="MAJOR"),
            Task(id="t4", task_type_id="tt_a", customer_id="c1", earliest_start=15, priority="MINOR"),
        ],
    )
    result = solve(request)
    assert result.status == "OPTIMAL"
    assert result_objective(result) == brute_force_optimum(request)
