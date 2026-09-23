"""Shared HTTP and engine contract. Source profiles remain assessment snapshots."""
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Grade = Literal["Junior", "Middle", "Senior", "Lead"]
Level = Annotated[int, Field(ge=0, le=5, strict=True)]
Identifier = Annotated[str, Field(min_length=1, max_length=100)]
Mode = Literal["mock", "live"]
Percent = Annotated[float, Field(ge=0, le=100)]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CareerGoal(Model):
    target_role: str
    target_grade: Grade


class Employee(Model):
    employee_id: Identifier
    full_name: str
    department: str
    role: str
    grade: Grade
    manager_id: Identifier | None
    hire_date: date
    tenure_months: Annotated[int, Field(ge=0)]
    work_format: Literal["office", "hybrid", "remote"]
    preferred_language: Literal["kk", "ru", "en"]
    career_goal: CareerGoal | None
    skills: dict[str, Level]
    last_review_date: date


class Skill(Model):
    skill_id: Identifier
    name: str
    type: Literal["hard", "soft"]
    category: str
    description: str


class RoleProfile(Model):
    role: str
    grade: Grade
    required_skills: dict[str, Level]
    critical_skills: list[str]


class Catalog(Model):
    proficiency_scale: dict[str, str]
    skills: list[Skill]
    role_profiles: list[RoleProfile]


class SkillGain(Model):
    skill_id: Identifier
    gain: Annotated[int, Field(ge=0, le=5, strict=True)]
    max_level: Level


class Event(Model):
    event_id: Identifier
    title: str
    description: str
    type: Literal["compliance", "onboarding", "course", "workshop", "mentoring", "certification", "meetup"]
    format: Literal["online", "offline", "self_paced"]
    duration_hours: Annotated[float, Field(gt=0)]
    mandatory: bool
    target_roles: list[str]
    target_grades: list[Grade]
    develops_skills: list[SkillGain]
    prerequisites: dict[str, Level]
    upcoming_sessions: list[date]


class HistoryRecord(Model):
    record_id: Identifier
    employee_id: Identifier
    event_id: Identifier
    date: date
    due_date: date | None
    status: Literal["completed", "in_progress", "dropped", "no_show", "declined", "overdue"]
    completion_pct: Annotated[int, Field(ge=0, le=100)]
    score: Annotated[int, Field(ge=0, le=100)] | None
    feedback_rating: Annotated[int, Field(ge=1, le=5)] | None
    assigned_by: Literal["self", "manager", "hr"]
    completed_at: date | None = None

    @model_validator(mode="after")
    def check_completed(self):
        if self.status == "completed" and self.completion_pct != 100:
            raise ValueError("completed requires completion_pct=100")
        if self.completed_at is not None and self.status != "completed":
            raise ValueError("completed_at requires completed status")
        return self


class EngineContext(Model):
    profile: Employee
    history: list[HistoryRecord]
    events: list[Event]
    catalog: Catalog
    as_of_date: date


class ActivityRequest(Model):
    event_id: Identifier
    session_date: date | None = None


class Recommendation(Model):
    event_id: Identifier
    title: str
    format: Literal["online", "offline", "self_paced"]
    duration_hours: float
    session_date: date | None
    reasons: list[str]
    score: float | None


class RecommendationResponse(Model):
    employee_id: Identifier
    as_of_date: date
    mode: Mode
    current_skills: dict[str, Level]
    progress_pct: Percent | None
    items: list[Recommendation]
    message: str


class SimulationResponse(Model):
    employee_id: Identifier
    event_id: Identifier
    as_of_date: date
    session_date: date | None
    mode: Mode
    skills_before: dict[str, Level]
    skills_after: dict[str, Level]
    progress_before_pct: Percent | None
    progress_after_pct: Percent | None
    message: str


class Completion(Model):
    completion_id: Identifier
    employee_id: Identifier
    event_id: Identifier
    session_date: date | None
    completed_on: date
    created_at: datetime
    history_record_id: Identifier
    result: SimulationResponse


class CompletionResponse(Model):
    completion: Completion
    replayed: bool


class EmployeePage(Model):
    items: list[Employee]
    total: int
    offset: int
    limit: int


class EventList(Model):
    items: list[Event]


class HistoryList(Model):
    items: list[HistoryRecord]


class CompletionList(Model):
    items: list[Completion]


class Health(Model):
    status: Literal["ok"]
    engine_mode: Mode
    as_of_date: date
    dataset_loaded: bool
