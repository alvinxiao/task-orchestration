
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
    MAJOR = "MAJOR"
    MINOR = "MINOR"


PRIORITY_WEIGHT = {
    Priority.CRITICAL: 4,
    Priority.MAJOR: 2,
    Priority.MINOR: 1,
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


class SolveOptions(BaseModel):
    time_limit_seconds: float = Field(strict=True, gt=0, allow_inf_nan=False)


class PlanningRequest(BaseModel):
    employees: list[Employee] = Field(default_factory=list)
    customers: list[Customer] = Field(default_factory=list)
    task_types: list[TaskType] = Field(default_factory=list)
    tasks: list[Task] = Field(default_factory=list)
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
        return self



class TaskAssignment(BaseModel):
    task_id: str
    start: int
    finish: int
    duration: int


class EmployeeSchedule(BaseModel):
    employee_id: str
    tasks: list[TaskAssignment]


class UnassignedTask(BaseModel):
    task_id: str
    reason: str


class ObjectiveComponents(BaseModel):
    squared_employee_finish_cost: int
    weighted_task_completion_cost: int


class SolveResult(BaseModel):
    status: str
    assignments: list[EmployeeSchedule]
    unassigned: list[UnassignedTask]
    makespan: int
    objective: ObjectiveComponents
    best_bound: int | None
    elapsed_seconds: float
