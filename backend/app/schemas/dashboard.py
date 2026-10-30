from uuid import UUID

from pydantic import Field

from app.schemas.common import Schema


class LeaderboardEntry(Schema):
    dataset_id: UUID
    dataset_name: str
    version_id: UUID
    study_id: UUID
    status: str
    baseline_validation_fit: float | None = Field(
        default=None, description="正式确定性 Baseline 的验证自由仿真 FIT。"
    )
    optimized_validation_fit: float | None = Field(
        default=None, description="Best Trial 的验证自由仿真 FIT。"
    )
    optimized_test_fit: float | None = Field(
        default=None, description="Best Trial 固定后仅执行一次的 held-out Test 自由仿真 FIT。"
    )
    optimized_test_one_step_fit: float | None = None
    optimized_test_one_step_r2: float | None = None
    optimized_test_free_run_r2: float | None = None
    improvement: float | None = None
    generalization_gap: float | None = None
    baseline_available: bool = False
    test_available: bool = False
    generalization_risk: str = "unavailable"
    risk_message: str = "暂无测试集评价"
    contribution_summary: str | None = None


class DashboardLeaderboardData(Schema):
    items: list[LeaderboardEntry] = Field(default_factory=list)
