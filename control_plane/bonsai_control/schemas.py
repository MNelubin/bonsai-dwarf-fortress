from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class JobCreate(BaseModel):
    objective_id: UUID | None = None
    job_type: str = "research_cycle"
    priority: int = Field(default=100, ge=-1000, le=1000)
    payload: dict[str, Any] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)
    base_commit: str | None = None
    max_attempts: int = Field(default=2, ge=1, le=10)


class JobResult(BaseModel):
    status: Literal["completed", "candidate", "rejected"] = "completed"
    result: dict[str, Any] = Field(default_factory=dict)
    artifact_hashes: list[str] = Field(default_factory=list)


class JobFailure(BaseModel):
    error: str = Field(min_length=1, max_length=20_000)
    retryable: bool = True


class Heartbeat(BaseModel):
    progress: dict[str, Any] = Field(default_factory=dict)


class WorkerHeartbeat(BaseModel):
    status: Literal["idle", "running", "error"]
    model: str = Field(min_length=1, max_length=200)
    harness: str = Field(default="opencode", min_length=1, max_length=100)
    version: str = Field(default="unknown", min_length=1, max_length=100)
    current_job_id: UUID | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ObjectiveCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str = ""
    priority: int = Field(default=100, ge=-1000, le=1000)
    cycle_interval_seconds: int = Field(default=300, ge=30, le=86_400)


class ControllerSubmissionCreate(BaseModel):
    objective_id: UUID
    git_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_job_id: UUID | None = None
    manifest: dict[str, Any] = Field(default_factory=dict)
