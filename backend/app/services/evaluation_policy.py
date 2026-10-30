"""Single source of truth for formal optimisation evaluation policy."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal


@dataclass(frozen=True)
class BaselineConfig:
    """Deterministic engineer-default pipeline used before Optuna starts."""

    window_size: int = 60
    max_segments: int = 10
    min_segment_length: int = 100
    max_missing_ratio: float = 0.20
    max_anomaly_ratio: float = 0.10
    min_input_activity_ratio: float = 0.05
    selection_na: int = 2
    selection_nb: int = 2
    selection_nk: int = 0
    na: int = 2
    nb: int = 2
    nk: int = 0
    estimator: Literal["ols", "ridge"] = "ols"
    ridge_alpha: float | None = None
    train_ratio: float = 0.60
    validation_ratio: float = 0.20

    @property
    def test_ratio(self) -> float:
        return 1.0 - self.train_ratio - self.validation_ratio

    def to_payload(
        self,
        *,
        input_columns: list[str],
        train_ratio: float | None = None,
        validation_ratio: float | None = None,
    ) -> dict[str, object]:
        """Serialise every default, including channel-expanded ARX orders."""

        payload = asdict(self)
        actual_train_ratio = self.train_ratio if train_ratio is None else train_ratio
        actual_validation_ratio = (
            self.validation_ratio if validation_ratio is None else validation_ratio
        )
        payload["train_ratio"] = actual_train_ratio
        payload["validation_ratio"] = actual_validation_ratio
        payload["test_ratio"] = 1.0 - actual_train_ratio - actual_validation_ratio
        payload["input_columns"] = list(input_columns)
        payload["nb_by_input"] = {column: self.nb for column in input_columns}
        payload["nk_by_input"] = {column: self.nk for column in input_columns}
        return payload


DEFAULT_BASELINE_CONFIG = BaselineConfig()

# Engineering display thresholds, not an industry-standard failure criterion.
GENERALIZATION_GAP_ATTENTION = 10.0
GENERALIZATION_GAP_HIGH_RISK = 25.0


def generalization_risk(
    gap: float | None,
) -> tuple[Literal["unavailable", "normal", "attention", "high"], str]:
    if gap is None:
        return "unavailable", "暂无测试集评价"
    if gap <= GENERALIZATION_GAP_ATTENTION:
        return "normal", "系统工程风险提示：泛化差距正常"
    if gap <= GENERALIZATION_GAP_HIGH_RISK:
        return "attention", "系统工程风险提示：请关注泛化差距"
    return "high", "系统工程风险提示：泛化风险高"
