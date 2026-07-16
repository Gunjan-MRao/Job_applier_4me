from pydantic import BaseModel, Field
from typing import Any, Optional, Literal
from datetime import datetime


RunStatus = Literal["pending", "running", "completed", "failed", "needs_review"]
StepStatus = Literal["started", "completed", "failed", "warning"]


class WorkflowRunCreate(BaseModel):
    workflow_name: str
    candidate_name: Optional[str] = None
    candidate_email: Optional[str] = None
    target_role: Optional[str] = None
    notes: Optional[str] = None
    input_payload: Optional[dict[str, Any]] = None


class WorkflowRunResponse(BaseModel):
    run_id: str
    workflow_name: str
    status: RunStatus
    candidate_name: Optional[str] = None
    candidate_email: Optional[str] = None
    target_role: Optional[str] = None
    notes: Optional[str] = None
    input_payload: Optional[dict[str, Any]] = None
    started_at: datetime
    updated_at: datetime


class StepEventCreate(BaseModel):
    step_name: str
    step_type: str = "generic"
    status: StepStatus
    message: Optional[str] = None
    input_summary: Optional[dict[str, Any]] = None
    output_summary: Optional[dict[str, Any]] = None
    error_text: Optional[str] = None
    latency_ms: Optional[int] = None


class StepEventResponse(BaseModel):
    event_id: str
    run_id: str
    step_name: str
    step_type: str
    status: StepStatus
    message: Optional[str] = None
    input_summary: Optional[dict[str, Any]] = None
    output_summary: Optional[dict[str, Any]] = None
    error_text: Optional[str] = None
    latency_ms: Optional[int] = None
    created_at: datetime


class MonitorIssue(BaseModel):
    severity: Literal["low", "medium", "high"]
    code: str
    message: str
    step_name: Optional[str] = None


class RunAuditResponse(BaseModel):
    run_id: str
    workflow_name: str
    run_status: RunStatus
    issues: list[MonitorIssue] = Field(default_factory=list)
    total_events: int
    failed_events: int
    warning_events: int