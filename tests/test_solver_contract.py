import pytest
from ortools.sat.python import cp_model

from task_orchestration import Customer, Employee, Task, TaskType, solve
from task_orchestration import solver as implementation
from helpers import make_request


def request(release=0, count=1):
    return make_request(
        [Employee(id=str(i), name=str(i), customer_affinities={"c": "HIGH"}) for i in range(count)],
        [Customer(id="c", name="C")], [TaskType(id="tt", base_duration=1)],
        [Task(id="t", task_type_id="tt", customer_id="c", earliest_start=release, priority="MAJOR")],
    )


def test_safe_horizon_above_old_cap():
    result = solve(request(100_000_000))
    assert result.status == "OPTIMAL"
    assert result.makespan == 100_000_001
    assert result.best_bound == result.objective.squared_employee_finish_cost + result.objective.weighted_task_completion_cost


def test_large_objective_exact_bound():
    result = solve(request(99_999_998))
    assert result.status == "OPTIMAL"
    assert result.best_bound == 9_999_999_999_999_999


def test_unsafe_objective_domains_rejected():
    with pytest.raises(ValueError, match="integer limits"):
        solve(request(99_999_999, 500))


@pytest.mark.parametrize("code,name", [(cp_model.UNKNOWN, "UNKNOWN"), (cp_model.INFEASIBLE, "INFEASIBLE"), (cp_model.MODEL_INVALID, "MODEL_INVALID")])
def test_no_incumbent_statuses(monkeypatch, code, name):
    monkeypatch.setattr(cp_model.CpSolver, "Solve", lambda self, model: code)
    result = solve(request())
    assert result.status == name
    assert result.assignments == []
    assert result.best_bound is None


def test_feasible_incumbent_is_returned(monkeypatch):
    actual = cp_model.CpSolver.Solve
    def feasible(self, model):
        assert actual(self, model) == cp_model.OPTIMAL
        return cp_model.FEASIBLE
    monkeypatch.setattr(cp_model.CpSolver, "Solve", feasible)
    result = solve(request())
    assert result.status == "FEASIBLE"
    assert result.assignments[0].tasks[0].task_id == "t"
    assert result.best_bound <= 3


def test_setup_exhaustion_skips_search(monkeypatch):
    ticks = iter([0.0, 11.0, 12.0])
    monkeypatch.setattr(implementation.time, "perf_counter", lambda: next(ticks))
    def forbidden(*args):
        pytest.fail("search ran after budget exhaustion")
    monkeypatch.setattr(cp_model.CpSolver, "Solve", forbidden)
    result = solve(request())
    assert result.status == "UNKNOWN"
    assert result.elapsed_seconds == 12.0


def test_setup_consumes_search_budget_and_extraction_counts(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(implementation.time, "perf_counter", lambda: clock[0])
    validate = cp_model.CpModel.Validate
    actual = cp_model.CpSolver.Solve
    compact = implementation._compact
    def validated(self):
        clock[0] = 2.0
        return validate(self)
    def searched(self, model):
        assert self.parameters.max_time_in_seconds == 8.0
        result = actual(self, model)
        clock[0] = 3.0
        return result
    def extracted(*args):
        clock[0] = 4.0
        return compact(*args)
    monkeypatch.setattr(cp_model.CpModel, "Validate", validated)
    monkeypatch.setattr(cp_model.CpSolver, "Solve", searched)
    monkeypatch.setattr(implementation, "_compact", extracted)
    assert solve(request()).elapsed_seconds == 4.0
