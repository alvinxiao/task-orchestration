import pytest
from ortools.sat.python import cp_model

from task_orchestration import Customer, Employee, Task, TaskType, solve
from task_orchestration import solver as implementation
from helpers import make_request


def request(release=0, count=1):
    return make_request(
        [Employee(id=str(i), name=str(i), customer_affinities={"c": "HIGH"}) for i in range(count)],
        [Customer(id="c", name="C")], [TaskType(id="tt", base_duration=1)],
        [Task(id="t", task_type_id="tt", customer_id="c", earliest_start=release, priority="HIGH")],
    )


def test_safe_horizon_above_old_cap():
    result = solve(request(100_000_000))
    assert result.status == "OPTIMAL"
    assert not result.provisional
    assert result.makespan == 100_000_001
    high_stage = next(record for record in result.stages if record.name == "HIGH")
    assert high_stage.proven
    assert high_stage.bound == high_stage.value == 100_000_001


def test_large_stage_value_exact_bound():
    result = solve(request(99_999_998))
    assert result.status == "OPTIMAL"
    high_stage = next(record for record in result.stages if record.name == "HIGH")
    assert high_stage.value == high_stage.bound == 99_999_999
    assert result.objective.priority_completion_totals["HIGH"] == 99_999_999


def test_unsafe_stage_domains_rejected():
    with pytest.raises(ValueError, match="integer limits"):
        solve(request(99_999_999, 500))


@pytest.mark.parametrize("code,name", [(cp_model.UNKNOWN, "UNKNOWN"), (cp_model.INFEASIBLE, "INFEASIBLE"), (cp_model.MODEL_INVALID, "MODEL_INVALID")])
def test_no_incumbent_statuses(monkeypatch, code, name):
    monkeypatch.setattr(cp_model.CpSolver, "Solve", lambda self, model: code)
    result = solve(request())
    assert result.status == name
    assert result.provisional
    assert result.assignments == []
    assert all(record.bound is None for record in result.stages if not record.proven)


def test_feasible_first_stage_stops_provisional(monkeypatch):
    actual = cp_model.CpSolver.Solve
    calls = []
    def feasible(self, model):
        calls.append(1)
        assert actual(self, model) == cp_model.OPTIMAL
        return cp_model.FEASIBLE
    monkeypatch.setattr(cp_model.CpSolver, "Solve", feasible)
    result = solve(request())
    assert result.status == "FEASIBLE"
    assert result.provisional
    assert len(calls) == 1
    assert result.assignments[0].tasks[0].task_id == "t"
    assert result.proven_priorities == ["CRITICAL"]
    high_stage = next(record for record in result.stages if record.name == "HIGH")
    assert high_stage.status == "FEASIBLE" and not high_stage.proven
    assert high_stage.value is not None
    assert next(record for record in result.stages if record.name == "FAIRNESS").status == "NOT_RUN"


def test_unknown_later_stage_retains_incumbent(monkeypatch):
    actual = cp_model.CpSolver.Solve
    def optimal_then_unknown(self, model):
        if not hasattr(self, "_called"):
            self._called = True
            actual(self, model)
            return cp_model.OPTIMAL
        return cp_model.UNKNOWN
    monkeypatch.setattr(cp_model.CpSolver, "Solve", optimal_then_unknown)
    two_priority = make_request(
        [Employee(id="e1", name="Ann", skills={"a"})],
        [Customer(id="c", name="C")],
        [TaskType(id="tt", base_duration=1)],
        [
            Task(id="critical", task_type_id="tt", customer_id="c", earliest_start=0, priority="CRITICAL"),
            Task(id="low", task_type_id="tt", customer_id="c", earliest_start=0, priority="LOW"),
        ],
    )
    result = solve(two_priority)
    assert result.status == "FEASIBLE"
    assert result.provisional
    assert result.proven_priorities == ["CRITICAL", "HIGH", "MEDIUM"]
    assigned = [item.task_id for schedule in result.assignments for item in schedule.tasks]
    assert sorted(assigned) == ["critical", "low"]
    assert result.objective.priority_completion_totals["CRITICAL"] == 4
    assert next(record for record in result.stages if record.name == "LOW").status == "UNKNOWN"
    assert next(record for record in result.stages if record.name == "FAIRNESS").status == "NOT_RUN"


def test_shared_budget_covers_all_stages(monkeypatch):
    clock = [0.0]
    budgets = []
    monkeypatch.setattr(implementation.time, "perf_counter", lambda: clock[0])
    actual = cp_model.CpSolver.Solve
    def searched(self, model):
        budgets.append(self.parameters.max_time_in_seconds)
        clock[0] += 1.0
        return actual(self, model)
    monkeypatch.setattr(cp_model.CpSolver, "Solve", searched)
    two_priority = make_request(
        [Employee(id="e1", name="Ann", skills={"a"})],
        [Customer(id="c", name="C")],
        [TaskType(id="tt", base_duration=1)],
        [
            Task(id="critical", task_type_id="tt", customer_id="c", earliest_start=0, priority="CRITICAL"),
            Task(id="low", task_type_id="tt", customer_id="c", earliest_start=0, priority="LOW"),
        ],
        time_limit=5.0,
    )
    result = solve(two_priority)
    assert result.status == "OPTIMAL"
    assert len(budgets) == 3  # CRITICAL, LOW, FAIRNESS stages
    assert budgets[0] <= 5.0
    assert all(budget <= 5.0 for budget in budgets)
    assert budgets == sorted(budgets, reverse=True)
    assert all(budget > 0 for budget in budgets)
    assert result.elapsed_seconds == 3.0


def test_setup_exhaustion_skips_search(monkeypatch):
    ticks = iter([0.0, 11.0, 12.0])
    monkeypatch.setattr(implementation.time, "perf_counter", lambda: next(ticks))
    def forbidden(*args):
        pytest.fail("search ran after budget exhaustion")
    monkeypatch.setattr(cp_model.CpSolver, "Solve", forbidden)
    result = solve(request())
    assert result.status == "UNKNOWN"
    assert result.provisional
    assert result.elapsed_seconds == 12.0


def test_setup_consumes_stage_budget_and_extraction_counts(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(implementation.time, "perf_counter", lambda: clock[0])
    validate = cp_model.CpModel.Validate
    actual = cp_model.CpSolver.Solve
    budgets = []
    def validated(self):
        clock[0] = max(clock[0], 2.0)
        return validate(self)
    def searched(self, model):
        budgets.append(self.parameters.max_time_in_seconds)
        result = actual(self, model)
        clock[0] += 1.0
        return result
    monkeypatch.setattr(cp_model.CpModel, "Validate", validated)
    monkeypatch.setattr(cp_model.CpSolver, "Solve", searched)
    result = solve(request())
    assert result.status == "OPTIMAL"
    # Validate runs before each of the HIGH and FAIRNESS stage solves and its
    # setup time comes out of the same shared budget.
    assert budgets == [8.0, 7.0]
    assert result.elapsed_seconds == 4.0


def test_validation_runs_per_stage(monkeypatch):
    validate = cp_model.CpModel.Validate
    calls = []
    def counted(self):
        calls.append(1)
        return validate(self)
    monkeypatch.setattr(cp_model.CpModel, "Validate", counted)
    result = solve(request())
    assert result.status == "OPTIMAL"
    # HIGH stage plus fairness stage, each validated before its solve.
    assert len(calls) == 2


def test_stage_values_do_not_use_float_objective(monkeypatch):
    from ortools.sat.python import cp_model
    def forbidden(self):
        pytest.fail("stage locks must use exact integer values")
    monkeypatch.setattr(cp_model.CpSolver, "ObjectiveValue", forbidden)
    result = solve(request())
    assert result.status == "OPTIMAL"
    for stage in result.stages:
        assert stage.proven
