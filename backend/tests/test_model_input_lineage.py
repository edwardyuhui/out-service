import asyncio
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import numpy as np
import pytest
from app.services import version_data

from test_optimization import make_series


@pytest.mark.parametrize("aligned", [True, False])
def test_removed_input_context_requires_row_and_output_alignment(monkeypatch, tmp_path, aligned):
    parent = make_series(n_samples=300)
    parent = replace(parent, values={**parent.values, "heater": np.full(300, 135.)},
                     declared_inputs=(*parent.declared_inputs, "heater"))
    output = parent.values["y"].copy()
    if not aligned:
        output[20] += 1.
    child = replace(parent, version_id=uuid4(), values={c: v for c, v in parent.values.items() if c != "heater"})
    child = replace(child, values={**child.values, "y": output}, declared_inputs=parent.declared_inputs[:-1])
    async def get(_model, version_id):
        return SimpleNamespace(operation_name="preprocessing.feature_selection", parent_version_id=parent.version_id) if version_id == child.version_id else None
    async def load(*args, **kwargs):
        return parent
    monkeypatch.setattr(version_data, "load_version_series", load)
    session = SimpleNamespace(get=get)
    if not aligned:
        with pytest.raises(version_data.VersionDataError, match="无法逐行对齐"):
            asyncio.run(version_data.attach_model_input_context(session, child, artifact_root=tmp_path))
    else:
        series = asyncio.run(version_data.attach_model_input_context(session, child, artifact_root=tmp_path))
        assert series.declared_inputs == child.declared_inputs
        assert series.monitored_inputs == ("heater",)
        assert series.input_context_versions["heater"] == str(parent.version_id)
        assert "heater" in version_data.model_input_arrays(series, list(child.declared_inputs))
