from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from app.schemas.common import Schema, TaskResource


class CopilotChatRequest(Schema):
    message: str = Field(min_length=1, max_length=8_000)
    dataset_id: UUID | None = None
    active_version_id: UUID | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class ExecutionPlanStep(Schema):
    step_id: str
    tool: Literal[
        "profile_dataset",
        "align_and_resample",
        "detect_anomalies",
        "clean_data",
        "detect_dynamic_segments",
        "estimate_delays",
        "apply_lag_compensation",
        "analyze_collinearity",
        "select_variables",
        "fit_arx",
        "evaluate_model",
        "optimize_pipeline",
        "generate_report",
        "export_dataset",
    ]
    depends_on: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    requires_confirmation: bool = False
    status: Literal["pending", "waiting_confirmation", "running", "completed", "failed"] = "pending"


class ExecutionPlan(Schema):
    goal: str
    dataset_id: UUID | None = None
    steps: list[ExecutionPlanStep]
    stop_conditions: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class ProofCheckData(Schema):
    """One statically verified property of an execution plan."""

    name: str
    passed: bool
    detail: str


class ComplianceProofData(Schema):
    """Machine-checked evidence that a plan obeys the frozen safety rules.

    A plan whose proof does not pass is never executed, so this is the record of what was
    verified rather than a promise about what the agent intends to do.
    """

    proof_id: str
    passed: bool
    checks: list[ProofCheckData]
    signature: str
    code_version: str
    generated_at: str


class AgentStepRun(Schema):
    """One executed step: its inputs, its real tool output and its timing."""

    step_id: str
    tool: str
    status: Literal["pending", "waiting_confirmation", "running", "completed", "failed"]
    parameters: dict[str, Any] = Field(default_factory=dict)
    summary: str
    result: dict[str, Any] = Field(default_factory=dict)
    duration_ms: float = 0.0
    error_code: str | None = None


class CopilotChatData(Schema):
    copilot_run_id: UUID
    execution_id: UUID | None = None
    workflow_status: str | None = None
    current_version_id: UUID | None = None
    pending_confirmation_step_id: str | None = None
    plan: ExecutionPlan
    task: TaskResource | None = None
    compliance: ComplianceProofData | None = None
    step_runs: list[AgentStepRun] = Field(default_factory=list)
    conclusion: str = ""
    executed: bool = False
    # Where the plan came from. "llm" means a model authored it and it then passed the same
    # whitelist and compliance checks a rule-based plan passes; "rule_based" means the
    # deterministic planner produced it, either by configuration or after a fallback.
    plan_source: Literal["llm", "rule_based"] = "rule_based"
    llm_provider: str = "none"
    llm_model: str = "none"
    llm_fallback_reason: str | None = None


class LagOverrideEntry(Schema):
    """One explicit human override row, kept as input rather than inferred by the Agent."""

    variable: str = Field(min_length=1, max_length=255)
    value: Any


class LagOverrideParameterValidation(Schema):
    variable: str
    recommended_value: int | None = None
    manual_value: Any | None = None
    final_value: int | None = None
    status: Literal["VALID", "WARNING", "INVALID"]
    issues: list[str] = Field(default_factory=list)


class LagOverrideValidationRequest(Schema):
    execution_id: UUID
    step_id: str = Field(min_length=1)
    manual_overrides: list[LagOverrideEntry] = Field(default_factory=list)


class LagOverrideValidationData(Schema):
    recommended_lag_map: dict[str, int]
    manual_overrides: dict[str, Any]
    final_lag_map: dict[str, int]
    parameter_sources: dict[str, Literal["delay_recommendation", "manual_override"]]
    disposition: Literal["APPLY_VERSION", "CONFIRMED_NO_OP"] = "APPLY_VERSION"
    per_parameter_validation: list[LagOverrideParameterValidation] = Field(default_factory=list)
    overall_status: Literal["VALID", "WARNING", "INVALID"]
    issues: list[str] = Field(default_factory=list)


class FeatureSelectionValidationRequest(Schema):
    execution_id: UUID
    step_id: str = Field(min_length=1)
    drop_columns: list[str] | None = None


class FeatureSelectionDecision(Schema):
    variable: str
    recommended_action: Literal["keep", "drop", "merge", "review"]
    final_action: Literal["keep", "drop"]
    source: Literal["collinearity_analysis", "manual_override"]


class FeatureSelectionValidationData(Schema):
    recommended_selection: dict[str, Literal["keep", "drop", "merge", "review"]]
    recommended_drop_columns: list[str]
    manual_drop_columns: list[str] | None = None
    final_drop_columns: list[str]
    kept_input_columns: list[str]
    selection_sources: dict[str, Literal["collinearity_analysis", "manual_override"]]
    decisions: list[FeatureSelectionDecision] = Field(default_factory=list)
    overall_status: Literal["VALID", "INVALID"]
    issues: list[str] = Field(default_factory=list)

class ArxStructureManualOverrides(Schema):
    na: Any | None = None
    nb: dict[str, Any] = Field(default_factory=dict)


class ArxStructureValidationRequest(Schema):
    execution_id: UUID
    step_id: str = Field(min_length=1)
    manual_overrides: ArxStructureManualOverrides = Field(
        default_factory=ArxStructureManualOverrides
    )


class ArxStructureValidationData(Schema):
    recommended_structure: dict[str, Any]
    manual_overrides: dict[str, Any]
    final_structure: dict[str, Any]
    structure_sources: dict[str, Literal["structure_recommendation", "manual_override"]]
    selection_evidence: dict[str, Any]
    overall_status: Literal["VALID", "INVALID"]
    issues: list[str] = Field(default_factory=list)

class CopilotConfirmRequest(Schema):
    copilot_run_id: UUID
    confirmation_id: str = Field(min_length=1)
    approved: bool
    execution_id: UUID | None = None
    step_id: str | None = Field(default=None, min_length=1)
    parameter_overrides: dict[str, Any] = Field(default_factory=dict)
    manual_overrides: list[LagOverrideEntry] = Field(default_factory=list)
    warning_acknowledged: bool = False
    feature_drop_columns: list[str] | None = None
    arx_structure_overrides: ArxStructureManualOverrides = Field(
        default_factory=ArxStructureManualOverrides
    )
    comment: str | None = Field(default=None, max_length=2_000)


class CopilotConfirmData(Schema):
    copilot_run_id: UUID
    confirmation_id: str
    decision: Literal["approved", "rejected"]
    execution_id: UUID
    workflow_status: str
    current_version_id: UUID | None = None
    current_step_id: str | None
    pending_confirmation_step_id: str | None
    step_id: str
    step_status: str
    confirmation_status: str
    result_version_id: UUID | None = None
    result_payload: dict[str, Any] = Field(default_factory=dict)
    lag_override_validation: LagOverrideValidationData | None = None
    feature_selection_validation: FeatureSelectionValidationData | None = None
    arx_structure_validation: ArxStructureValidationData | None = None
    task: TaskResource | None = None

class CopilotStepExecutionData(Schema):
    execution_id: UUID
    workflow_status: str
    current_version_id: UUID | None = None
    step_id: str
    step_status: str
    result_payload: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    processing_run_ids: list[str] = Field(default_factory=list)


class CopilotExecutionStepSnapshot(Schema):
    step_id: str
    sequence: int
    tool: str
    status: str
    requires_confirmation: bool
    confirmation_status: str
    attempt_count: int
    source_version_id: UUID | None = None
    result_version_id: UUID | None = None
    input_payload: dict[str, Any] = Field(default_factory=dict)
    result_payload: dict[str, Any] = Field(default_factory=dict)
    processing_run_ids: list[str] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class CopilotExecutionSnapshotData(Schema):
    execution_id: UUID
    copilot_run_id: UUID | None = None
    dataset_id: UUID
    initial_version_id: UUID
    current_version_id: UUID
    planner_source: str
    workflow_status: str
    current_step_id: str | None = None
    pending_confirmation_step_id: str | None = None
    plan: ExecutionPlan
    artifacts: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None
    step_runs: list[CopilotExecutionStepSnapshot] = Field(default_factory=list)


class OptimizePipelineExecuteRequest(Schema):
    execution_id: UUID


class CopilotOptimizePipelineExecuteData(CopilotStepExecutionData):
    pass

class CopilotEvaluateModelExecuteRequest(Schema):
    execution_id: UUID


class CopilotEvaluateModelExecuteData(CopilotStepExecutionData):
    pass
