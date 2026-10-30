import pytest
from algorithms.agent.llm_planner import _coerce_steps
from algorithms.agent.planner import RuleBasedPlanner, parse_intent
from app.services.agent_tool_adapter import _OPTIMIZATION_PARAMETER_NAMES


def test_explicit_strict_validation_survives_rule_plan_and_tool_adapter():
    intent = parse_intent("用全折验收寻优，执行4次迭代并生成报告")
    steps, _, _ = RuleBasedPlanner().plan(intent)
    optimize = next(s for s in steps if s.tool == "optimize_pipeline")
    assert optimize.parameters == {"max_trials": 4, "optimization_policy": "validation_guarded"}
    assert set(optimize.parameters) <= _OPTIMIZATION_PARAMETER_NAMES


@pytest.mark.parametrize("parameters", [{"optimization_policy": "imaginary"}, {"diagnose_feedback": "false"}])
def test_cloud_plan_cannot_invent_policy_or_use_string_booleans(parameters):
    with pytest.raises(ValueError):
        _coerce_steps({"steps": [{"tool": "optimize_pipeline", "parameters": parameters}]})
