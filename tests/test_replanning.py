
import pytest
from pydantic import ValidationError

from task_orchestration import (
    CommittedRecord,
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
from ortools.sat.python import cp_model

from helpers import make_request


def base_request(tasks, replanning=None, employees=None):
    return make_request(
        employees if employees is not None else [
            Employee(id="e1", name="Ann", skills={"a"}),
            Employee(id="e2", name="Bob", skills={"a"}),
        ],
        [Customer(id="c1", name="Alpha")],
        [TaskType(id="tt", base_duration=10, required_skills={"a"})],
        tasks,
        replanning=replanning,
    )


def assignments_by_task(result):
    return {
        item.task_id: (schedule.employee_id, item)
        for schedule in result.assignments
        for item in schedule.tasks
    }


def stage_names(result):
    return [record.name for record in result.stages]


def _low(task_id):
    return Task(id=task_id, task_type_id="tt", customer_id="c1", earliest_start=0, priority="LOW")


def test_urgent_arrival_replanned_from_current_time():
    tasks = [
        Task(id="t1", task_type_id="tt", customer_id="c1", earliest_start=0, priority="LOW"),
        Task(id="t2", task_type_id="tt", customer_id="c1", earliest_start=0, priority="MEDIUM"),
    ]
    first = solve(base_request(tasks))
    assert first.status == "OPTIMAL"
    urgent = Task(id="urgent", task_type_id="tt", customer_id="c1", earliest_start=0, priority="CRITICAL")
    replanning = ReplanningContext(
        current_time=40,
        completed_task_ids=["t1"],
        in_progress=[InProgressRecord(task_id="t2", employee_id="e1", actual_start=0, remaining_minutes=20)],
        previous_assignments=[
            PreviousAssignmentRecord(task_id=item[1].task_id, employee_id=item[0], start=item[1].start)
            for item in assignments_by_task(first).values()
        ],
    )
    result = solve(base_request([urgent, tasks[0], tasks[1]], replanning=replanning))
    assert result.status == "OPTIMAL"
    assert not result.provisional
    by_task = assignments_by_task(result)
    assert "t1" not in by_task
    assert by_task["urgent"][1].start >= 40
    assert by_task["urgent"][0] == "e2" or by_task["urgent"][1].start >= 60


def test_no_pending_work_starts_in_the_past_or_before_release():
    replanning = ReplanningContext(
        current_time=50,
        in_progress=[InProgressRecord(task_id="running", employee_id="e1", actual_start=10, remaining_minutes=30)],
    )
    request = base_request(
        [
            Task(id="running", task_type_id="tt", customer_id="c1", earliest_start=0, priority="HIGH"),
            Task(id="later", task_type_id="tt", customer_id="c1", earliest_start=120, priority="LOW"),
        ],
        replanning=replanning,
    )
    result = solve(request)
    assert result.status == "OPTIMAL"
    by_task = assignments_by_task(result)
    assert by_task["later"][1].start >= 120
    for task_id, (employee_id, item) in by_task.items():
        if task_id != "running":
            assert item.start >= 50


def test_in_progress_task_is_not_rescheduled_and_keeps_actual_start():
    replanning = ReplanningContext(
        current_time=60,
        in_progress=[InProgressRecord(task_id="running", employee_id="e2", actual_start=15, remaining_minutes=25)],
    )
    result = solve(base_request(
        [Task(id="running", task_type_id="tt", customer_id="c1", earliest_start=0, priority="HIGH")],
        replanning=replanning,
    ))
    assert result.status == "OPTIMAL"
    employee_id, item = assignments_by_task(result)["running"]
    assert employee_id == "e2"
    assert item.start == 15
    assert item.actual_start == 15
    assert item.finish == 85
    assert item.duration == 25
    assert item.in_progress is True
    assert result.makespan == 85


def test_in_progress_occupies_remaining_minutes_and_fairness_counts_only_remaining():
    replanning = ReplanningContext(
        current_time=60,
        in_progress=[InProgressRecord(task_id="running", employee_id="e1", actual_start=0, remaining_minutes=10)],
    )
    request = base_request(
        [
            Task(id="running", task_type_id="tt", customer_id="c1", earliest_start=0, priority="LOW"),
            Task(id="p1", task_type_id="tt", customer_id="c1", earliest_start=0, priority="LOW"),
            Task(id="p2", task_type_id="tt", customer_id="c1", earliest_start=0, priority="LOW"),
        ],
        replanning=replanning,
    )
    result = solve(request)
    assert result.status == "OPTIMAL"
    # Both pending tasks fit next to the 10 remaining minutes on e1, and
    # fairness balances remaining work: loads 50 and 40, not the full 110.
    assert sorted(result.objective.employee_work_minutes.values()) == [40, 50]
    assert result.objective.squared_load_cost == 50**2 + 40**2
    # The in-progress finish (current_time + remaining = 70) counts in totals.
    by_task = assignments_by_task(result)
    assert by_task["running"][1].finish == 70
    low_total = sum(
        item.finish for _, item in by_task.values()
    )
    assert result.objective.priority_completion_totals["LOW"] == low_total


def test_completed_tasks_are_excluded_from_output_and_objectives():
    replanning = ReplanningContext(
        current_time=30,
        completed_task_ids=["done"],
        in_progress=[InProgressRecord(task_id="running", employee_id="e1", actual_start=0, remaining_minutes=10)],
    )
    result = solve(base_request(
        [
            Task(id="done", task_type_id="tt", customer_id="c1", earliest_start=0, priority="CRITICAL"),
            Task(id="running", task_type_id="tt", customer_id="c1", earliest_start=0, priority="HIGH"),
        ],
        replanning=replanning,
    ))
    assert result.status == "OPTIMAL"
    by_task = assignments_by_task(result)
    assert "done" not in by_task
    assert all(item.task_id != "done" for item in result.unassigned)
    assert result.objective.priority_completion_totals["CRITICAL"] == 0
    assert result.objective.priority_completion_totals["HIGH"] == 40
    assert result.objective.employee_work_minutes == {"e1": 10, "e2": 0}


def test_committed_task_stays_fixed_and_pending_work_fits_around_it():
    replanning = ReplanningContext(
        current_time=0,
        committed=[CommittedRecord(task_id="locked", employee_id="e1", start=100)],
    )
    request = base_request(
        [
            Task(id="locked", task_type_id="tt", customer_id="c1", earliest_start=0, priority="HIGH"),
            Task(id="free", task_type_id="tt", customer_id="c1", earliest_start=0, priority="LOW"),
        ],
        replanning=replanning,
    )
    result = solve(request)
    assert result.status == "OPTIMAL"
    by_task = assignments_by_task(result)
    employee_id, item = by_task["locked"]
    assert employee_id == "e1"
    assert item.start == 100
    assert item.finish == 140
    assert item.duration == 40
    # e2 can take the free task during e1's reserved window.
    assert by_task["free"][1].finish <= 100 or by_task["free"][0] == "e2"


def test_fixed_interval_conflicts_are_rejected():
    in_progress = ReplanningContext(
        current_time=50,
        in_progress=[InProgressRecord(task_id="running", employee_id="e1", actual_start=0, remaining_minutes=30)],
        committed=[CommittedRecord(task_id="locked", employee_id="e1", start=60)],
    )
    with pytest.raises(ValueError, match="fixed intervals overlap"):
        solve(base_request(
            [
                Task(id="running", task_type_id="tt", customer_id="c1", earliest_start=0, priority="HIGH"),
                Task(id="locked", task_type_id="tt", customer_id="c1", earliest_start=0, priority="LOW"),
            ],
            replanning=in_progress,
        ))

    two_committed = ReplanningContext(
        current_time=0,
        committed=[
            CommittedRecord(task_id="c1t", employee_id="e1", start=20),
            CommittedRecord(task_id="c2t", employee_id="e1", start=30),
        ],
    )
    with pytest.raises(ValueError, match="fixed intervals overlap"):
        solve(base_request(
            [
                Task(id="c1t", task_type_id="tt", customer_id="c1", earliest_start=0, priority="HIGH"),
                Task(id="c2t", task_type_id="tt", customer_id="c1", earliest_start=0, priority="LOW"),
            ],
            replanning=two_committed,
        ))


def test_committed_task_with_unqualified_employee_rejected():
    replanning = ReplanningContext(
        current_time=0,
        committed=[CommittedRecord(task_id="locked", employee_id="e2", start=10)],
    )
    request = make_request(
        [
            Employee(id="e1", name="Ann", skills={"a"}),
            Employee(id="e2", name="Bob", skills={"b"}),
        ],
        [Customer(id="c1", name="Alpha")],
        [TaskType(id="tt", base_duration=10, required_skills={"a"})],
        [Task(id="locked", task_type_id="tt", customer_id="c1", earliest_start=0, priority="HIGH")],
        replanning=replanning,
    )
    with pytest.raises(ValueError, match="requires skills"):
        solve(request)


def test_in_progress_employee_must_exist():
    with pytest.raises(ValidationError, match="unknown employee"):
        base_request(
            [Task(id="t1", task_type_id="tt", customer_id="c1", earliest_start=0, priority="LOW")],
            replanning=ReplanningContext(
                current_time=10,
                in_progress=[InProgressRecord(task_id="t1", employee_id="ghost", actual_start=0, remaining_minutes=5)],
            ),
        )


def test_in_progress_skills_are_grandfathered():
    request = make_request(
        [
            Employee(id="e1", name="Ann", skills={"a"}),
            Employee(id="e2", name="Bob", skills={"a"}),
        ],
        [Customer(id="c1", name="Alpha")],
        [TaskType(id="tt", base_duration=10, required_skills={"a"})],
        [Task(id="running", task_type_id="tt", customer_id="c1", earliest_start=0, priority="HIGH")],
        replanning=ReplanningContext(
            current_time=20,
            in_progress=[InProgressRecord(task_id="running", employee_id="e1", actual_start=0, remaining_minutes=10)],
        ),
    )
    # e1 has the required skill; nothing here needs grandfathering, but the
    # record must still validate and solve with the employee preserved.
    result = solve(request)
    assert result.status == "OPTIMAL"
    assert assignments_by_task(result)["running"][0] == "e1"


@pytest.mark.parametrize(
    "tasks, context, match",
    [
        (
            [_low("t1")],
            ReplanningContext(
                current_time=30,
                in_progress=[InProgressRecord(task_id="t1", employee_id="e1", actual_start=40, remaining_minutes=5)],
            ),
            "after current time",
        ),
        (
            [_low("t1")],
            ReplanningContext(
                current_time=30,
                committed=[CommittedRecord(task_id="t1", employee_id="e1", start=20)],
            ),
            "before current time",
        ),
        (
            [_low("t1"), _low("t2")],
            dict(
                current_time=0,
                in_progress=[
                    InProgressRecord(task_id="t1", employee_id="e1", actual_start=0, remaining_minutes=5),
                    InProgressRecord(task_id="t2", employee_id="e1", actual_start=0, remaining_minutes=5),
                ],
            ),
            "more than one in-progress",
        ),
        (
            [_low("t1"), _low("t2")],
            dict(
                current_time=0,
                completed_task_ids=["t1", "t2"],
                in_progress=[InProgressRecord(task_id="t1", employee_id="e1", actual_start=0, remaining_minutes=5)],
            ),
            "more than one execution state",
        ),
        (
            [_low("t1")],
            dict(completed_task_ids=["missing"]),
            "not in the request tasks",
        ),
        (
            [_low("t1")],
            dict(
                previous_assignments=[PreviousAssignmentRecord(task_id="t1", employee_id="ghost", start=0)],
            ),
            "unknown employee",
        ),
        (
            [_low("t1")],
            dict(
                in_progress=[
                    InProgressRecord(task_id="t1", employee_id="e1", actual_start=0, remaining_minutes=5),
                    InProgressRecord(task_id="t1", employee_id="e2", actual_start=0, remaining_minutes=5),
                ],
            ),
            "duplicate task ids in replanning records",
        ),
        (
            [_low("t1")],
            dict(completed_task_ids=["t1", "t1"]),
            "duplicate completed task ids",
        ),
    ],
)
def test_invalid_execution_states_rejected_at_boundary(tasks, context, match):
    with pytest.raises(ValidationError, match=match):
        if not isinstance(context, ReplanningContext):
            context = ReplanningContext(**context)
        base_request(tasks, replanning=context)


def test_stability_minimizes_changed_previous_assignments():
    previous = [
        PreviousAssignmentRecord(task_id="p1", employee_id="e1", start=0),
        PreviousAssignmentRecord(task_id="p2", employee_id="e2", start=0),
    ]
    # Urgent committed work now occupies e1 at p1's previous slot, so p1 must
    # move, but p2 can stay exactly where it was.
    context = ReplanningContext(
        current_time=0,
        committed=[CommittedRecord(task_id="urgent", employee_id="e1", start=0)],
        previous_assignments=previous,
    )
    result = solve(base_request(
        [
            Task(id="urgent", task_type_id="tt", customer_id="c1", earliest_start=0, priority="CRITICAL"),
            Task(id="p1", task_type_id="tt", customer_id="c1", earliest_start=0, priority="LOW"),
            Task(id="p2", task_type_id="tt", customer_id="c1", earliest_start=0, priority="LOW"),
        ],
        replanning=context,
    ))
    assert result.status == "OPTIMAL"
    assert result.stability is not None
    assert result.stability.changed_tasks == 1
    assert result.stability.unchanged_tasks == 1
    change = result.stability.changes[0]
    assert change.task_id == "p1"
    assert change.previous_employee_id == "e1"
    by_task = assignments_by_task(result)
    assert by_task["urgent"][0] == "e1" and by_task["urgent"][1].start == 0
    assert by_task["p2"][0] == "e2" and by_task["p2"][1].start == 0


def test_stability_runs_after_fairness_is_locked():
    previous = [PreviousAssignmentRecord(task_id="p1", employee_id="e2", start=0)]
    context = ReplanningContext(current_time=0, previous_assignments=previous)
    result = solve(base_request(
        [Task(id="p1", task_type_id="tt", customer_id="c1", earliest_start=0, priority="LOW")],
        replanning=context,
    ))
    assert result.status == "OPTIMAL"
    names = stage_names(result)
    assert names == ["CRITICAL", "HIGH", "MEDIUM", "LOW", "FAIRNESS", "STABILITY"]
    assert all(record.proven for record in result.stages)
    fairness = next(record for record in result.stages if record.name == "FAIRNESS")
    assert fairness.value == result.objective.squared_load_cost
    # Previous assignment e2/start 0 equals a stable optimum: nothing changed.
    assert result.stability.changed_tasks == 0
    assert result.objective.employee_work_minutes == {"e1": 0, "e2": 40}


def test_no_previous_assignments_skips_stability_stage():
    context = ReplanningContext(current_time=30)
    result = solve(base_request(
        [Task(id="t1", task_type_id="tt", customer_id="c1", earliest_start=0, priority="LOW")],
        replanning=context,
    ))
    assert stage_names(result) == ["CRITICAL", "HIGH", "MEDIUM", "LOW", "FAIRNESS"]
    assert result.stability is None


def test_request_without_replanning_keeps_old_behavior():
    result = solve(base_request(
        [
            Task(id="t1", task_type_id="tt", customer_id="c1", earliest_start=0, priority="CRITICAL"),
            Task(id="t2", task_type_id="tt", customer_id="c1", earliest_start=0, priority="LOW"),
        ],
    ))
    assert result.status == "OPTIMAL"
    assert stage_names(result) == ["CRITICAL", "HIGH", "MEDIUM", "LOW", "FAIRNESS"]
    assert result.stability is None
    assert result.proven_priorities == ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
    assert result.objective.priority_completion_totals["CRITICAL"] == 40


def test_timeout_later_stage_retains_incumbent_snapshot(monkeypatch):
    actual = cp_model.CpSolver.Solve
    def optimal_then_unknown(self, model):
        if not hasattr(self, "_called"):
            self._called = True
            actual(self, model)
            return cp_model.OPTIMAL
        return cp_model.UNKNOWN
    monkeypatch.setattr(cp_model.CpSolver, "Solve", optimal_then_unknown)
    context = ReplanningContext(
        current_time=0,
        previous_assignments=[PreviousAssignmentRecord(task_id="low", employee_id="e1", start=0)],
    )
    result = solve(base_request(
        [
            Task(id="critical", task_type_id="tt", customer_id="c1", earliest_start=0, priority="CRITICAL"),
            Task(id="low", task_type_id="tt", customer_id="c1", earliest_start=0, priority="LOW"),
        ],
        replanning=context,
    ))
    assert result.status == "FEASIBLE"
    assert result.provisional
    assert result.proven_priorities == ["CRITICAL", "HIGH", "MEDIUM"]
    assigned = sorted(assignments_by_task(result))
    assert assigned == ["critical", "low"]
    assert next(record for record in result.stages if record.name == "LOW").status == "UNKNOWN"
    assert next(record for record in result.stages if record.name == "STABILITY").status == "NOT_RUN"


def test_committed_job_cannot_start_before_release():
    task = Task(id="future", task_type_id="tt", customer_id="c1", earliest_start=100, priority="LOW")
    with pytest.raises(ValidationError, match="earliest start"):
        base_request([task], ReplanningContext(current_time=10, committed=[
            CommittedRecord(task_id="future", employee_id="e1", start=20)
        ]))
