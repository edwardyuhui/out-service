"""Trusted DatasetVersion lineage resolution shared by modeling workflows."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dataset import DatasetVersion


class VersionProvenanceError(Exception):
    """A DatasetVersion lineage cannot satisfy a modeling-stage invariant."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 422,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


async def resolve_arx_lag_provenance(
    session: AsyncSession,
    *,
    version_id: UUID,
    input_columns: list[str],
) -> tuple[dict[str, int], UUID]:
    """Resolve a direct Lag version or a Feature-only descendant to its Lag ancestor."""

    current_id: UUID | None = version_id
    visited: set[UUID] = set()
    while current_id is not None:
        if current_id in visited:
            raise _lag_provenance_required("lineage_cycle")
        visited.add(current_id)

        version = await session.get(DatasetVersion, current_id)
        if version is None:
            raise _lag_provenance_required("missing_version")
        if version.operation_name == "preprocessing.lag_compensation":
            lag_map = version.parameters.get("lag_map")
            if not isinstance(lag_map, dict) or any(
                column not in lag_map
                or isinstance(lag_map[column], bool)
                or not isinstance(lag_map[column], int)
                or lag_map[column] < 0
                for column in input_columns
            ):
                raise VersionProvenanceError(
                    "ARX_LAG_PROVENANCE_INCOMPLETE",
                    "时滞补偿版本没有使用合法非负整数覆盖当前全部输入变量。",
                )
            return dict.fromkeys(input_columns, 0), version.id
        if version.operation_name != "preprocessing.feature_selection":
            raise _lag_provenance_required(
                "unsupported_operation",
                operation_name=version.operation_name,
            )
        if version.parent_version_id is None:
            raise _lag_provenance_required("missing_parent")
        current_id = version.parent_version_id

    raise _lag_provenance_required("missing_parent")


def _lag_provenance_required(
    reason: str,
    *,
    operation_name: str | None = None,
) -> VersionProvenanceError:
    details: dict[str, object] = {"reason": reason}
    if operation_name is not None:
        details["operation_name"] = operation_name
    return VersionProvenanceError(
        "ARX_LAG_COMPENSATED_VERSION_REQUIRED",
        "当前数据版本缺少可信的时滞补偿血缘，无法执行 ARX 建模。",
        details=details,
    )


__all__ = ["VersionProvenanceError", "resolve_arx_lag_provenance"]
