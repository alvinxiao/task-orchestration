
import pytest
from pydantic import ValidationError

from task_orchestration import Customer, Employee, PlanningRequest, SolveOptions, Task, TaskType


def test_duplicate_employee_ids_rejected():
    with pytest.raises(ValidationError, match="duplicate ids"):
        PlanningRequest(
            employees=[Employee(id="e1", name="Ann"), Employee(id="e1", name="Bob")],
            customers=[],
            task_types=[],
            tasks=[],
            options=SolveOptions(time_limit_seconds=1),
        )


def test_unknown_task_type_reference_rejected():
    with pytest.raises(ValidationError, match="unknown task type"):
        _request(
            tasks=[Task(id="t1", task_type_id="missing", customer_id="c1", earliest_start=0, priority="MINOR")],
            task_types=[],
        )


def test_unknown_customer_reference_rejected():
    with pytest.raises(ValidationError, match="unknown customer"):
        _request(
            tasks=[Task(id="t1", task_type_id="tt", customer_id="missing", earliest_start=0, priority="MINOR")],
            task_types=[TaskType(id="tt", base_duration=10)],
        )


def test_unknown_affinity_customer_rejected():
    with pytest.raises(ValidationError, match="unknown customers"):
        _request(
            employees=[Employee(id="e1", name="Ann", customer_affinities={"ghost": "HIGH"})],
        )


def _request(**overrides):
    base = dict(
        employees=[],
        customers=[Customer(id="c1", name="Alpha")],
        task_types=[TaskType(id="tt", base_duration=10)],
        tasks=[],
    )
    base.update(overrides)
    return PlanningRequest(**base, options=SolveOptions(time_limit_seconds=1))


def test_non_positive_base_duration_rejected():
    with pytest.raises(ValidationError):
        TaskType(id="tt", base_duration=0, required_skills=set())


def test_negative_earliest_start_rejected():
    with pytest.raises(ValidationError):
        Task(id="t1", task_type_id="tt", customer_id="c1", earliest_start=-1, priority="MINOR")


def test_invalid_priority_rejected():
    with pytest.raises(ValidationError):
        Task(id="t1", task_type_id="tt", customer_id="c1", earliest_start=0, priority="URGENT")


def test_non_positive_time_limit_rejected():
    with pytest.raises(ValidationError):
        SolveOptions(time_limit_seconds=0)
    with pytest.raises(ValidationError):
        SolveOptions(time_limit_seconds=-1.0)


def test_empty_id_rejected():
    with pytest.raises(ValidationError):
        Customer(id="", name="Alpha")


def test_duplicate_task_ids_rejected():
    with pytest.raises(ValidationError, match="duplicate ids"):
        PlanningRequest(
            employees=[],
            customers=[Customer(id="c1", name="Alpha")],
            task_types=[TaskType(id="tt", base_duration=10)],
            tasks=[
                Task(id="t1", task_type_id="tt", customer_id="c1", earliest_start=0, priority="MINOR"),
                Task(id="t1", task_type_id="tt", customer_id="c1", earliest_start=0, priority="MINOR"),
            ],
            options=SolveOptions(time_limit_seconds=1),
        )


def test_non_string_earliest_start_rejected():
    with pytest.raises(ValidationError):
        Task(id="t1", task_type_id="tt", customer_id="c1", earliest_start="0", priority="MINOR")


@pytest.mark.parametrize("limit", [float("inf"), float("-inf"), float("nan")])
def test_non_finite_time_limit_rejected(limit):
    with pytest.raises(ValidationError):
        SolveOptions(time_limit_seconds=limit)
