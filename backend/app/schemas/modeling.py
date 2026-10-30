from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.common import Schema, TaskResource


class ArxFitRequest(Schema):
    version_id: UUID
    dataset_id: UUID | None = None
    input_columns: list[str] = Field(default_factory=list)
    output_column: str = "y"
    model_type: Literal["ARX", "FIR", "OE"] = "ARX"
    simulation_horizons: list[Annotated[int, Field(ge=0, le=4096)]] = Field(
        default_factory=lambda: [1, 16, 64, 0], min_length=1, max_length=8,
        description="OE 训练模拟时域；0 表示整个连续训练区间。",
    )
    simulation_max_nfev: int = Field(default=150, ge=1, le=500)
    na: int = Field(ge=0, le=100)
    regularization_kernel: Literal["identity", "tc"] = "identity"
    kernel_decay: float = Field(default=0.9, ge=0.1, le=0.99)
    initialization_policy: Literal["fixed", "past_residual"] = "fixed"
    initialization_window: int = Field(default=32, ge=8, le=128)
    nb: dict[str, int] | list[int] = Field(
        description="每个输入变量的 b 阶次；允许阶段 1 前端使用的同序数组。"
    )
    delays: dict[str, int] | list[int] = Field(
        description="每个输入变量的 nk；允许阶段 1 前端使用的同序数组。"
    )
    estimator: Literal["ols", "ridge", "huber"] = "ols"
    estimation_method: Literal["ols", "ridge", "huber"] | None = Field(
        default=None,
        description="阶段 1 前端兼容字段；优先于 estimator。",
    )
    ridge_alpha: float | None = Field(default=None, ge=0)
    train_ratio: float = Field(default=0.6, gt=0, lt=1)
    validation_ratio: float = Field(default=0.2, gt=0, lt=1)
    # Fitting is validation-only by default. The held-out Test partition is available
    # only to an explicit, post-selection evaluation path.
    evaluate_test: bool = False
    # Restrict the training rows to specific sample indices, e.g. the output of
    # quality-constrained D-optimal selection. Empty means "use every training row".
    training_sample_indices: list[int] = Field(default_factory=list)
    fit_intercept: bool = True
    standardize: bool = True
    huber_delta: float = Field(default=1.345, gt=0)
    history_guard: int | None = Field(default=None, ge=0)
    sample_weights: dict[int, Annotated[float, Field(ge=0, le=1)]] = Field(default_factory=dict)
    # Engineering priors. A model that violates them is rejected rather than reported,
    # because a gain with the wrong sign is not a slightly worse model, it is a wrong one.
    gain_sign: dict[str, Literal["positive", "negative"]] = Field(default_factory=dict)
    gain_bounds: dict[str, tuple[float, float]] = Field(default_factory=dict)
    require_stable: bool = False

    @model_validator(mode="after")
    def validate_model_family(self) -> "ArxFitRequest":
        if self.model_type == "OE":
            if not 1 <= self.na <= 4:
                raise ValueError("OE 分母阶数须为 1–4")
            if (self.resolved_estimator() != "ridge" or not self.fit_intercept
                    or not self.standardize or self.initialization_policy != "fixed"):
                raise ValueError("OE 要求 Ridge 初始化、标准化、截距及固定预测初始化")
            if len(set(self.simulation_horizons)) != len(self.simulation_horizons):
                raise ValueError("OE 模拟时域不能重复")
            if any(w not in (0., 1.) for w in self.sample_weights.values()):
                raise ValueError("OE 当前仅支持 0/1 样本权重；软权重请使用 ARX/FIR")
        if self.model_type == "ARX" and self.na < 1:
            raise ValueError("ARX 的 na 必须至少为 1")
        if self.model_type == "FIR" and self.na != 0:
            raise ValueError("FIR 的 na 必须为 0")
        if self.regularization_kernel == "tc" and (
            self.model_type != "FIR" or self.resolved_estimator() != "ridge"
            or not self.ridge_alpha or not self.standardize
        ):
            raise ValueError("TC 核要求 FIR、正则 Ridge 和标准化")
        return self

    def resolved_estimator(self) -> Literal["ols", "ridge", "huber"]:
        return self.estimation_method or self.estimator


class PriorViolation(Schema):
    """One engineering prior the identified model failed."""

    variable: str
    kind: Literal["gain_sign", "gain_bounds", "stability"]
    expected: str
    actual: float | None = None


class ModelValidationData(Schema):
    """Control-relevant acceptance evidence.

    ``free_run_fit`` is the primary metric: an APC controller predicts many steps ahead,
    so one-step FIT — which is fed the measured previous output — flatters any model on an
    autocorrelated process. ``one_step_fit`` is kept as a diagnostic, and a large
    ``fit_gap`` is itself the signal that the model is coasting on persistence.
    """

    one_step_fit: float | None = None
    free_run_fit: float | None = None
    free_run_rmse: float | None = None
    fit_gap: float | None = None
    stable: bool = True
    max_pole_modulus: float | None = None
    steady_state_gains: dict[str, float] = Field(default_factory=dict)
    residual_whiteness_ratio: float | None = None
    n_samples: int = Field(default=0, ge=0)
    input_residual_correlations: dict[str, list[float]] = Field(default_factory=dict)
    input_residual_test: dict[str, object] = Field(default_factory=dict)
    simulation_status: Literal["succeeded", "diverged"] = "succeeded"
    simulation_error_code: str | None = None
    initialization: dict[str, object] = Field(default_factory=dict)
    reference_baselines: dict[str, float | None] = Field(default_factory=dict)
    input_support: dict[str, object] = Field(default_factory=dict)
    partition: str = "validation"
    excitation_shortfall: dict[str, dict[str, int]] = Field(
        default_factory=dict,
        description=(
            "持续激励阶次低于 na+nb 的通道及其实际/所需阶次。"
            "这是诊断而非阻断：实测该判据无法区分可用与不可用的数据（见 ALG-0.2 §3）。"
        ),
    )


class PredictionMetrics(Schema):
    """Metrics calculated from one aligned actual/predicted sequence."""

    mae: float | None = None
    rmse: float | None = None
    r2: float | None = None
    fit: float | None = None
    nrmse: float | None = None


class ArxModelStructureData(Schema):
    """Stable public summary of the exact persisted ARX configuration."""

    model_type: Literal["ARX", "FIR", "OE"] = "ARX"
    simulation_horizons: list[int] = Field(default_factory=lambda: [1, 16, 64, 0])
    simulation_max_nfev: int = 150
    regularization_kernel: Literal["identity", "tc"] = "identity"
    kernel_decay: float = 0.9
    initialization_policy: Literal["fixed", "past_residual"] = "fixed"
    initialization_window: int = 32
    input_columns: list[str]
    output_column: str
    na: int = Field(ge=0)
    nb: dict[str, int]
    delays: dict[str, int]
    estimator: Literal["ols", "ridge", "huber"]
    fit_intercept: bool = False
    standardize: bool = False
    history_guard: int | None = None
    ridge_alpha: float | None = Field(default=None, ge=0)
    parameter_count: int = Field(ge=1)


class ArxEvaluationSeries(Schema):
    """Aligned observations, predictions and residuals from held-out Test only."""

    sample_indices: list[int]
    timestamps: list[datetime] = Field(default_factory=list)
    y_true: list[float]
    one_step_prediction: list[float]
    free_run_prediction: list[float]
    one_step_residual: list[float]
    free_run_residual: list[float]


class ArxModelHealth(Schema):
    """Partition-independent properties of the evaluated model itself."""

    stable: bool
    max_pole_modulus: float | None = None
    input_support: dict[str, object] = Field(default_factory=dict)


class ArxEvaluationResidualDiagnostics(Schema):
    """Held-out Test diagnostics computed from one-step residuals."""

    partition: Literal["test"] = "test"
    residual_type: Literal["one_step"] = "one_step"
    residual_whiteness_ratio: float | None = None
    acf_values: list[float]
    confidence_interval: float | None = None


class ArxTestEvaluationData(Schema):
    """Held-out Test metrics for one immutable, already-trained ARX model."""

    one_step: PredictionMetrics
    free_run: PredictionMetrics
    n_samples: int = Field(ge=0)


class ArxSavedModelEvaluationData(Schema):
    """Final Test evaluation of a saved ARX model without parameter estimation."""

    model_id: UUID
    source_version_id: UUID
    processing_run_id: UUID
    evaluation_scope: Literal["test"] = "test"
    model_structure: ArxModelStructureData
    model_health: ArxModelHealth
    test: ArxTestEvaluationData
    series: ArxEvaluationSeries
    residual_diagnostics: ArxEvaluationResidualDiagnostics


class ArxMetrics(Schema):
    """Compatibility metrics plus prediction-mode-explicit partition metrics.

    ``test_r2`` / ``test_rmse`` / ``mae`` historically mean one-step values. New code
    must use ``one_step`` or ``free_run`` below so a value is never detached from the
    prediction mode that produced it.
    """

    one_step: dict[str, PredictionMetrics] = Field(default_factory=dict)
    free_run: dict[str, PredictionMetrics] = Field(default_factory=dict)
    # Deprecated compatibility aliases for one-step metrics.
    train_r2: float | None = None
    train_fit: float | None = None
    train_rmse: float | None = None
    val_r2: float | None = None
    val_fit: float | None = None
    val_rmse: float | None = None
    test_r2: float | None = None
    test_fit: float | None = None
    test_rmse: float | None = None
    rmse: float | None = None
    mae: float | None = None
    nrmse: float | None = None
    # Free-run (infinite-step) simulation FIT per partition — the primary metric.
    train_free_run_fit: float | None = None
    val_free_run_fit: float | None = None
    test_free_run_fit: float | None = None
    aic: float | None = None
    bic: float | None = None


class SplitIndices(Schema):
    train_end: int = Field(ge=0)
    val_end: int = Field(ge=0)
    test_end: int = Field(ge=0)


class ArxPlotData(Schema):
    indices: list[int]
    y_true: list[float]
    y_pred: list[float]
    residuals: list[float]
    splits: SplitIndices
    split_indices: SplitIndices | None = None


class ArxResidualDiagnostics(Schema):
    acf_values: list[float]
    confidence_interval: float | None = None


class ArxFitData(Schema):
    model_id: UUID
    processing_run_id: UUID
    task: TaskResource
    estimator: Literal["ols", "ridge", "huber"]
    intercept: float = 0.0
    preprocessing: dict[str, object] = Field(default_factory=dict)
    model_structure: ArxModelStructureData
    dataset_id: UUID | None = None
    version_id: UUID | None = None
    coefficients: dict[str, float]
    a_coefficients: list[float] = Field(default_factory=list)
    b_coefficients: dict[str, list[float]] = Field(default_factory=dict)
    metrics: ArxMetrics
    plot_data: ArxPlotData
    residual_diagnostics: ArxResidualDiagnostics
    artifact_uri: str | None = None
    validation: ModelValidationData | None = None
    prior_violations: list[PriorViolation] = Field(default_factory=list)
    training_rows: int = Field(default=0, ge=0)
    free_run_series: list[float] = Field(default_factory=list)
