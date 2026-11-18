
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator


class Affinity(StrEnum):
    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


AFFINITY_MULTIPLIER = {
    Affinity.NONE: 4,
    Affinity.LOW: 3,
    Affinity.MEDIUM: 2,
    Affinity.HIGH: 1,
}

DEFAULT_AFFINITY = Affinity.NONE


class Priority(StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


PRIORITY_ORDER = [
    Priority.CRITICAL,
    Priority.HIGH,
    Priority.MEDIUM,
    Priority.LOW,
]

PRIORITY_ALIASES = {
    "MAJOR": Priority.HIGH,
    "MINOR": Priority.LOW,
}


class Customer(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)


class Employee(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    skills: set[str] = Field(default_factory=set)
    customer_affinities: dict[str, Affinity] = Field(default_factory=dict)


class TaskType(BaseModel):
    id: str = Field(min_length=1)
    base_duration: int = Field(strict=True, ge=1)
    required_skills: set[str] = Field(default_factory=set)


class Task(BaseModel):
    id: str = Field(min_length=1)
    task_type_id: str = Field(min_length=1)
    customer_id: str = Field(min_length=1)
    earliest_start: int = Field(strict=True, ge=0)
    priority: Priority

    @field_validator("priority", mode="before")
    @classmethod
    def _normalize_priority(cls, value):
        if isinstance(value, str):
            return PRIORITY_ALIASES.get(value, value)
        return value


class SolveOptions(BaseModel):
    time_limit_seconds: float = Field(strict=True, gt=0, allow_inf_nan=False)


class InProgressRecord(BaseModel):
    task_id: str = Field(min_length=1)
    employee_id: str = Field(min_length=1)
    actual_start: int = Field(strict=True, ge=0)
    remaining_minutes: int = Field(strict=True, ge=1)


class CommittedRecord(BaseModel):
    task_id: str = Field(min_length=1)
    employee_id: str = Field(min_length=1)
    start: int = Field(strict=True, ge=0)


class PreviousAssignmentRecord(BaseModel):
    task_id: str = Field(min_length=1)
    employee_id: str = Field(min_length=1)
    start: int = Field(strict=True, ge=0)


class ReplanningContext(BaseModel):
    current_time: int = Field(default=0, strict=True, ge=0)
    completed_task_ids: list[str] = Field(default_factory=list)
    in_progress: list[InProgressRecord] = Field(default_factory=list)
    committed: list[CommittedRecord] = Field(default_factory=list)
    previous_assignments: list[PreviousAssignmentRecord] = Field(default_factory=list)

    @field_validator("completed_task_ids")
    @classmethod
    def _unique_completed(cls, value: list[str]) -> list[str]:
        duplicates = {task_id for task_id in value if value.count(task_id) > 1}
        if duplicates:
            raise ValueError(f"duplicate completed task ids: {sorted(duplicates)}")
        return value

    @field_validator("in_progress", "committed", "previous_assignments")
    @classmethod
    def _unique_records(cls, value: list) -> list:
        ids = [item.task_id for item in value]
        duplicates = {task_id for task_id in ids if ids.count(task_id) > 1}
        if duplicates:
            raise ValueError(f"duplicate task ids in replanning records: {sorted(duplicates)}")
        return value


class PlanningRequest(BaseModel):
    employees: list[Employee] = Field(default_factory=list)
    customers: list[Customer] = Field(default_factory=list)
    task_types: list[TaskType] = Field(default_factory=list)
    tasks: list[Task] = Field(default_factory=list)
    replanning: ReplanningContext = Field(default_factory=ReplanningContext)
    options: SolveOptions

    @field_validator("employees", "customers", "task_types", "tasks")
    @classmethod
    def _unique_ids(cls, value: list) -> list:
        ids = [item.id for item in value]
        duplicates = {item_id for item_id in ids if ids.count(item_id) > 1}
        if duplicates:
            raise ValueError(f"duplicate ids: {sorted(duplicates)}")
        return value

    @model_validator(mode="after")
    def _validate_references(self) -> "PlanningRequest":
        customer_ids = {customer.id for customer in self.customers}
        task_type_ids = {task_type.id for task_type in self.task_types}
        for employee in self.employees:
            unknown = set(employee.customer_affinities) - customer_ids
            if unknown:
                raise ValueError(
                    f"employee {employee.id!r} has affinity for unknown customers: {sorted(unknown)}"
                )
        for task in self.tasks:
            if task.task_type_id not in task_type_ids:
                raise ValueError(f"task {task.id!r} references unknown task type {task.task_type_id!r}")
            if task.customer_id not in customer_ids:
                raise ValueError(f"task {task.id!r} references unknown customer {task.customer_id!r}")
        self._validate_replanning()
        return self

    def _validate_replanning(self) -> None:
        context = self.replanning
        task_ids = {task.id for task in self.tasks}
        employee_ids = {employee.id for employee in self.employees}
        for task_id in context.completed_task_ids:
            if task_id not in task_ids:
                raise ValueError(f"completed task {task_id!r} is not in the request tasks")
        in_progress_ids = {record.task_id for record in context.in_progress}
        committed_ids = {record.task_id for record in context.committed}
        overlap = (in_progress_ids & committed_ids)
        overlap |= (in_progress_ids & set(context.completed_task_ids))
        overlap |= (committed_ids & set(context.completed_task_ids))
        if overlap:
            raise ValueError(
                f"tasks appear in more than one execution state: {sorted(overlap)}"
            )
        for record in context.in_progress:
            if record.task_id not in task_ids:
                raise ValueError(f"in-progress task {record.task_id!r} is not in the request tasks")
            if record.employee_id not in employee_ids:
                raise ValueError(f"in-progress task {record.task_id!r} references unknown employee {record.employee_id!r}")
            if record.actual_start > context.current_time:
                raise ValueError(
                    f"in-progress task {record.task_id!r} starts at {record.actual_start} after current time {context.current_time}"
                )
        releases = {task.id: task.earliest_start for task in self.tasks}
        for record in context.committed:
            if record.task_id not in task_ids:
                raise ValueError(f"committed task {record.task_id!r} is not in the request tasks")
            if record.employee_id not in employee_ids:
                raise ValueError(f"committed task {record.task_id!r} references unknown employee {record.employee_id!r}")
            if record.start < releases[record.task_id]:
                raise ValueError(f"committed task {record.task_id!r} starts before its earliest start")
            if record.start < context.current_time:
                raise ValueError(
                    f"committed task {record.task_id!r} starts at {record.start} before current time {context.current_time}"
                )
        for record in context.previous_assignments:
            if record.task_id not in task_ids:
                raise ValueError(f"previous assignment {record.task_id!r} is not in the request tasks")
            if record.employee_id not in employee_ids:
                raise ValueError(f"previous assignment {record.task_id!r} references unknown employee {record.employee_id!r}")
        per_employee: dict[str, int] = {}
        for record in context.in_progress:
            if record.employee_id in per_employee:
                raise ValueError(
                    f"employee {record.employee_id!r} has more than one in-progress task"
                )
            per_employee[record.employee_id] = record.task_id



class TaskAssignment(BaseModel):
    task_id: str
    start: int
    finish: int
    duration: int
    actual_start: int | None = None
    in_progress: bool = False


class ReplanningChange(BaseModel):
    task_id: str
    previous_employee_id: str
    previous_start: int
    new_employee_id: str | None = None
    new_start: int | None = None


class StabilityMetrics(BaseModel):
    changed_tasks: int
    unchanged_tasks: int
    changes: list[ReplanningChange]


class EmployeeSchedule(BaseModel):
    employee_id: str
    tasks: list[TaskAssignment]


class UnassignedTask(BaseModel):
    task_id: str
    reason: str


class StageRecord(BaseModel):
    name: str
    status: str
    proven: bool
    value: int | None
    bound: int | None


class ObjectiveSummary(BaseModel):
    priority_completion_totals: dict[str, int]
    employee_work_minutes: dict[str, int]
    squared_load_cost: int


class SolveResult(BaseModel):
    status: str
    provisional: bool
    proven_priorities: list[str]
    stages: list[StageRecord]
    assignments: list[EmployeeSchedule]
    unassigned: list[UnassignedTask]
    makespan: int
    objective: ObjectiveSummary
    stability: StabilityMetrics | None = None
    elapsed_seconds: float
