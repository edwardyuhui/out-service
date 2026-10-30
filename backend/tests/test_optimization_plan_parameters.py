"""Regression checks for generated optimization parameters, without network access."""

import json
import unittest

from algorithms.agent.llm import StaticProvider
from algorithms.agent.llm_planner import LlmPlanner, _coerce_steps
from algorithms.agent.planner import RuleBasedPlanner, parse_intent


class OptimizationPlanParametersTest(unittest.TestCase):
    def parse(self, parameters):
        return _coerce_steps(
            {"steps": [{"tool": "optimize_pipeline", "parameters": parameters}]}
        )[0]

    def test_trial_alias_is_normalized_before_confirmation(self):
        step = self.parse({"n_trials": 10})
        self.assertEqual(step.parameters, {"max_trials": 10})
        self.assertTrue(step.requires_confirmation)

    def test_canonical_and_matching_alias(self):
        for parameters in ({"max_trials": 10}, {"max_trials": 10, "n_trials": 10}):
            self.assertEqual(self.parse(parameters).parameters, {"max_trials": 10})

    def test_conflicting_alias_is_rejected(self):
        with self.assertRaises(ValueError):
            self.parse({"max_trials": 10, "n_trials": 20})

    def test_invalid_trial_counts_are_rejected(self):
        for key in ("n_trials", "max_trials"):
            for value in (0, -1, 10001, True, 1.5, "10", None):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    self.parse({key: value})

    def test_unknown_parameter_is_rejected(self):
        with self.assertRaises(ValueError):
            self.parse({"trials": 10})

    def test_other_allowed_parameters_are_preserved(self):
        parameters = {
            "max_trials": 10, "timeout_seconds": 30, "random_seed": 42,
            "search_space": {"na": [1, 3]},
        }
        self.assertEqual(self.parse(parameters).parameters, parameters)
        self.assertEqual(self.parse({}).parameters, {})

    def plan(self, parameters):
        message = "请完成时滞补偿和 ARX 建模，进行 10 次试验的参数寻优"
        intent = parse_intent(message)
        steps, _, _ = RuleBasedPlanner().plan(intent)
        payload = {"steps": [
            {
                "step_id": step.step_id,
                "tool": step.tool,
                "depends_on": list(step.depends_on),
                "parameters": parameters if step.tool == "optimize_pipeline" else step.parameters,
            }
            for step in steps
        ]}
        provider = StaticProvider(responses=[json.dumps(payload)])
        return LlmPlanner(provider).plan(message, intent)

    def test_normalized_plan_passes_compliance_and_keeps_confirmation(self):
        outcome = self.plan({"n_trials": 10})
        self.assertTrue(outcome.llm_authored, outcome.fallback_reason)
        step = next(step for step in outcome.steps if step.tool == "optimize_pipeline")
        self.assertEqual(step.parameters, {"max_trials": 10})
        self.assertTrue(step.requires_confirmation)

    def test_conflicting_plan_uses_existing_rule_fallback(self):
        outcome = self.plan({"n_trials": 20, "max_trials": 10})
        self.assertFalse(outcome.llm_authored)
        self.assertIn("n_trials", outcome.fallback_reason)
        step = next(step for step in outcome.steps if step.tool == "optimize_pipeline")
        self.assertEqual(step.parameters, {"max_trials": 10})
