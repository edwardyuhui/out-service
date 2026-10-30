"""Focused tests for the shared ARX Lag-provenance resolver."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.models.dataset import DatasetVersion
from app.services.version_provenance_service import (
    VersionProvenanceError,
    resolve_arx_lag_provenance,
)


@dataclass
class VersionStub:
    operation_name: str
    parent_version_id: UUID | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    id: UUID = field(default_factory=uuid4)


class SessionStub:
    def __init__(self, *versions: VersionStub) -> None:
        self.versions = {version.id: version for version in versions}

    async def get(self, model: type[DatasetVersion], version_id: UUID) -> VersionStub | None:
        assert model is DatasetVersion
        return self.versions.get(version_id)


def resolve(
    session: SessionStub,
    version_id: UUID,
    input_columns: list[str] | None = None,
) -> tuple[dict[str, int], UUID]:
    return asyncio.run(
        resolve_arx_lag_provenance(
            session,  # type: ignore[arg-type]
            version_id=version_id,
            input_columns=input_columns or ["u1"],
        )
    )


def test_direct_lag_and_multi_level_feature_descendant_are_allowed() -> None:
    lag = VersionStub(
        "preprocessing.lag_compensation",
        parameters={"lag_map": {"u1": 3, "u2": 8}},
    )
    feature_one = VersionStub("preprocessing.feature_selection", parent_version_id=lag.id)
    feature_two = VersionStub("preprocessing.feature_selection", parent_version_id=feature_one.id)
    session = SessionStub(lag, feature_one, feature_two)

    assert resolve(session, lag.id, ["u1", "u2"]) == ({"u1": 0, "u2": 0}, lag.id)
    assert resolve(session, feature_two.id) == ({"u1": 0}, lag.id)


@pytest.mark.parametrize("operation_name", ["simulation_generate", "raw_upload", "preprocessing.clean", "custom.operation"])
def test_unsupported_source_operations_are_rejected(operation_name: str) -> None:
    source = VersionStub(operation_name)

    with pytest.raises(VersionProvenanceError) as raised:
        resolve(SessionStub(source), source.id)

    assert raised.value.code == "ARX_LAG_COMPENSATED_VERSION_REQUIRED"
    assert raised.value.status_code == 422
    assert raised.value.details["reason"] == "unsupported_operation"


def test_feature_with_missing_or_broken_parent_is_rejected() -> None:
    missing_parent = VersionStub("preprocessing.feature_selection")
    broken_parent = VersionStub("preprocessing.feature_selection", parent_version_id=uuid4())

    with pytest.raises(VersionProvenanceError) as missing:
        resolve(SessionStub(missing_parent), missing_parent.id)
    with pytest.raises(VersionProvenanceError) as broken:
        resolve(SessionStub(broken_parent), broken_parent.id)

    assert missing.value.details["reason"] == "missing_parent"
    assert broken.value.details["reason"] == "missing_version"


def test_feature_lineage_cycle_is_rejected() -> None:
    first = VersionStub("preprocessing.feature_selection")
    second = VersionStub("preprocessing.feature_selection", parent_version_id=first.id)
    first.parent_version_id = second.id

    with pytest.raises(VersionProvenanceError) as raised:
        resolve(SessionStub(first, second), first.id)

    assert raised.value.code == "ARX_LAG_COMPENSATED_VERSION_REQUIRED"
    assert raised.value.details["reason"] == "lineage_cycle"


def test_lag_map_must_cover_every_selected_input_with_non_negative_integers() -> None:
    lag = VersionStub(
        "preprocessing.lag_compensation",
        parameters={"lag_map": {"u1": 3}},
    )

    with pytest.raises(VersionProvenanceError) as raised:
        resolve(SessionStub(lag), lag.id, ["u1", "u2"])

    assert raised.value.code == "ARX_LAG_PROVENANCE_INCOMPLETE"
    assert raised.value.status_code == 422
