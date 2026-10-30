"""LLM-authored plans and report narration, constrained by the existing validators.

The model is given the tool whitelist and asked for a JSON plan. What comes back is then
put through exactly the checks a rule-based plan goes through — unknown tool names, cycles,
dangling dependencies, test-partition access and high-impact gating — so the LLM's role is
to *propose*, never to authorise.

Report narration is constrained harder still: the model is told it may not write digits,
and :func:`algorithms.report.provenance.validate_draft` rejects the draft if it does. That
turns "please do not hallucinate numbers" from a request into a property of the pipeline.

Every path degrades to the deterministic implementation. A missing API key, an unreachable
Ollama, a malformed completion and a plan that fails its proof all land in the same place:
the rule-based result, plus a stated reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from algorithms.agent.compliance import verify_plan
from algorithms.agent.llm import (
    LlmMessage,
    LlmProvider,
    LlmUnavailableError,
    extract_json,
)
from algorithms.agent.planner import (
    CONFIRMATION_REQUIRED,
    TOOL_WHITELIST,
    ParsedIntent,
    PlannedStep,
    RuleBasedPlanner,
)

PLANNER_SYSTEM_PROMPT = f"""你是流程工业建模数据预处理系统的调度中枢。
把工程师的自然语言需求拆解为结构化工作流，只能使用以下工具，不得发明新工具：

{", ".join(TOOL_WHITELIST)}

严格输出 JSON，不要输出任何解释文字，格式为：
{{
  "steps": [
    {{"step_id": "s1", "tool": "profile_dataset", "depends_on": [], "parameters": {{}}}}
  ],
  "assumptions": ["..."]
}}

规则：
1. 第一步必须是 profile_dataset。
2. clean_data 必须在 detect_anomalies 之后；evaluate_model 必须在 fit_arx 之后。
3. select_variables、optimize_pipeline、export_dataset 属于高影响操作。
4. parameters 只填工程师明确给出的数值（如窗口长度、最大滞后、试验次数），不要臆造。
5. 不得引用测试集，不得让任何拟合型变换使用训练集以外的数据。
6. 若工作流包含 fit_arx（ARX 辨识），必须在其前面安排 estimate_delays（估计时滞）与 apply_lag_compensation（时滞补偿），因为工业时序 ARX 建模必须基于已完成时滞补偿对齐的数据版本。
7. “报告交付”、report delivery 只表示 generate_report；只有用户明确要求导出/下载数据集或 CSV（包括优选、最优、最优建模数据集）时才允许添加 export_dataset。
8. 若建模寻优任务明确要求导出数据集，顺序必须是 optimize_pipeline、evaluate_model、export_dataset。
9. optimize_pipeline 的试验次数使用 max_trials（1 到 10000 的整数），不要使用 n_trials。该工具接受 max_trials、timeout_seconds、random_seed、search_space、optimization_policy、diagnose_feedback 参数。
10. 用户明确要求“全折验收”“全折验证”或“严格验证”时，optimization_policy 必须为 validation_guarded；其他合法策略为 established、paired_coverage、disturbance_aware。diagnose_feedback 必须为布尔值。不要自行开启实验策略。"""

NARRATOR_SYSTEM_PROMPT = """你是工业过程辨识专家，负责撰写建模数据优选与辨识报告的结论段落。
首句交代数据分区用途：Train 拟合参数，Validation 验证模型，Test 固定参数评价。
Test 是评价区间，不得称作参数训练、拟合或完成辨识的区间。

**硬性规则：你绝对不能写出任何数字。** 一个阿拉伯数字都不许出现在正文里。
所有数值必须使用用户消息给出的 run 或 step 占位符，原样保留引用种类、编号和字段路径，由系统从持久化证据解析后填入。

可用的运行编号与字段路径会在用户消息中给出。只能引用给定的路径，不得臆造字段。
输出简短中文段落，依据给出的真实指标解释数据优选、辨识效果与局限。
只写一到两个短段落，不罗列运行编号。TC 的名称写作 TC 核正则化，含义为随滞后衰减的脉冲响应先验。
仅在 TC 核启用时解释 kernel_decay；仅在 past_residual 策略启用时解释初始化窗口。
闭环寻优调整的是数据预处理参数，不是设备操作点或控制设定值。
输入阶次 nb 的数值不是输入通道名称。不要把模型生成时间当成采集时间或工况区间。
FIT 非正意味着自由仿真误差达到或超过该区间自身波动，必须明确说明效果不足。
结构稳定性不代表预测准确；没有现场验证，不能宣称模型具备投运条件或可用于控制器部署。
不要输出 Markdown 标题，只输出正文段落。"""


@dataclass
class PlanOutcome:
    """A plan plus how it was produced, so the UI can be honest about provenance."""

    steps: list[PlannedStep]
    assumptions: list[str]
    stop_conditions: list[str]
    source: str = "rule_based"
    provider: str = "none"
    model: str = "none"
    fallback_reason: str | None = None
    raw_completion: str = ""
    latency_ms: float = 0.0

    @property
    def llm_authored(self) -> bool:
        return self.source == "llm"


@dataclass
class NarrationOutcome:
    """An LLM narrative that passed the numeral check, or the reason it did not."""

    text: str = ""
    source: str = "template"
    provider: str = "none"
    model: str = "none"
    fallback_reason: str | None = None
    attempts: int = 0
    violations: list[dict[str, Any]] = field(default_factory=list)


class LlmPlanner:
    """Ask the model for a plan; accept it only if it survives every validator."""

    def __init__(self, provider: LlmProvider, *, code_version: str = "1.0.0") -> None:
        self._provider = provider
        self._code_version = code_version
        self._fallback = RuleBasedPlanner()

    def plan(
        self,
        message: str,
        intent: ParsedIntent,
        *,
        lag_ready: bool | None = None,
    ) -> PlanOutcome:
        steps, assumptions, stop_conditions = self._fallback.plan(intent)
        baseline = PlanOutcome(
            steps=steps,
            assumptions=list(assumptions),
            stop_conditions=list(stop_conditions),
        )

        try:
            result = self._provider.complete(
                [
                    LlmMessage(role="system", content=PLANNER_SYSTEM_PROMPT),
                    LlmMessage(role="user", content=message),
                ]
            )
        except LlmUnavailableError as error:
            baseline.fallback_reason = str(error)
            return baseline

        try:
            payload = extract_json(result.text)
            candidate = _coerce_steps(payload)
        except (ValueError, KeyError, TypeError) as error:
            baseline.fallback_reason = f"大模型输出无法解析为合法计划：{error}"
            baseline.provider, baseline.model = result.provider, result.model
            baseline.raw_completion = result.text
            return baseline

        if not candidate:
            baseline.fallback_reason = "大模型返回了空计划。"
            baseline.provider, baseline.model = result.provider, result.model
            baseline.raw_completion = result.text
            return baseline

        explicit_policy = intent.parameters.get("optimization_policy")
        if explicit_policy:
            if not any(step.tool == "optimize_pipeline" for step in candidate):
                baseline.fallback_reason = "大模型未包含用户明确要求的全折验收寻优。"
                baseline.provider, baseline.model = result.provider, result.model
                return baseline
            candidate = [replace(step, parameters={**step.parameters, "optimization_policy": explicit_policy})
                if step.tool == "optimize_pipeline" else step for step in candidate]

        if not intent.wants("export") and any(
            step.tool == "export_dataset" for step in candidate
        ):
            baseline.fallback_reason = "大模型计划包含用户未明确要求的数据集导出步骤。"
            baseline.provider, baseline.model = result.provider, result.model
            baseline.raw_completion = result.text
            return baseline

        export_restored = False
        if intent.wants("export") and not any(
            step.tool == "export_dataset" for step in candidate
        ):
            used_step_ids = {step.step_id for step in candidate}
            step_number = len(candidate) + 1
            while f"s{step_number}" in used_step_ids:
                step_number += 1
            candidate.append(
                PlannedStep(
                    step_id=f"s{step_number}",
                    tool="export_dataset",
                    depends_on=(candidate[-1].step_id,),
                    parameters={},
                    requires_confirmation="export_dataset" in CONFIRMATION_REQUIRED,
                )
            )
            export_restored = True

        proof = verify_plan(
            [
                {
                    "step_id": step.step_id,
                    "tool": step.tool,
                    "depends_on": list(step.depends_on),
                    "parameters": dict(step.parameters),
                    "requires_confirmation": step.requires_confirmation,
                }
                for step in candidate
            ],
            code_version=self._code_version,
            lag_ready=lag_ready,
        )
        if not proof.passed:
            # The model proposed something the rules forbid. Falling back is the safe
            # outcome, and the reason is surfaced rather than swallowed.
            baseline.fallback_reason = "大模型计划未通过合规校验：" + "；".join(
                check.detail for check in proof.failures
            )
            baseline.provider, baseline.model = result.provider, result.model
            baseline.raw_completion = result.text
            return baseline

        llm_assumptions = list(_coerce_assumptions(payload))
        if export_restored:
            llm_assumptions.append(
                "检测到明确的数据集导出意图，系统已补充需人工确认的 export_dataset 步骤。"
            )
        llm_assumptions.append(
            f"本计划由大模型 {result.provider}/{result.model} 生成，并已通过白名单与合规静态校验。"
        )
        return PlanOutcome(
            steps=candidate,
            assumptions=llm_assumptions + list(assumptions),
            stop_conditions=list(stop_conditions),
            source="llm",
            provider=result.provider,
            model=result.model,
            raw_completion=result.text,
            latency_ms=result.latency_ms,
        )


class LlmNarrator:
    """Ask the model for prose; reject it if it contains a single unbound digit."""

    def __init__(self, provider: LlmProvider, *, max_attempts: int = 3) -> None:
        self._provider = provider
        self._max_attempts = max_attempts

    def narrate(self, *, context: str, available_paths: list[str],
                reference_kinds: dict[str, str] | None = None) -> NarrationOutcome:
        from algorithms.report.provenance import PLACEHOLDER_PATTERN, validate_draft

        outcome = NarrationOutcome()
        kinds = reference_kinds or {}
        allowed = {(kinds.get(path.split(".", 1)[0], "run"), path) for path in available_paths}
        paths = "\n".join(f"- {{{{{kinds.get(path.split('.', 1)[0], 'run')}:{path}}}}}" for path in available_paths)
        user_message = f"{context}\n\n可引用的占位符：\n{paths}"

        for attempt in range(1, self._max_attempts + 1):
            outcome.attempts = attempt
            try:
                result = self._provider.complete(
                    [
                        LlmMessage(role="system", content=NARRATOR_SYSTEM_PROMPT),
                        LlmMessage(role="user", content=user_message),
                    ],
                    temperature=0.2,
                )
            except LlmUnavailableError as error:
                outcome.fallback_reason = str(error)
                return outcome

            outcome.provider, outcome.model = result.provider, result.model
            violations = validate_draft(result.text)
            unknown = [match.group(0) for match in PLACEHOLDER_PATTERN.finditer(result.text)
                if (match.group(1), f"{match.group(2)}.{match.group(3)}") not in allowed]
            if not violations and not unknown:
                outcome.text = result.text.strip()
                outcome.source = "llm"
                return outcome

            outcome.violations = [violation.to_payload() for violation in violations[:10]]
            outcome.violations.extend({"text": reference, "reason": "UNKNOWN_REPORT_REFERENCE"} for reference in unknown[:10])
            user_message = (
                f"{context}\n\n可引用的占位符：\n{paths}\n\n"
                f"上一次输出被拒绝，因为它包含未溯源数字或未知引用："
                f"{', '.join([*(violation.text for violation in violations[:5]), *unknown[:5]])}。"
                "请重写，任何数值都必须引用清单中确实存在的占位符。"
            )

        outcome.fallback_reason = (
            f"大模型连续 {self._max_attempts} 次输出未溯源数字或未知引用，已回退到模板化结论。"
        )
        return outcome


def _coerce_steps(payload: Any) -> list[PlannedStep]:
    """Turn raw model output into typed steps, rejecting anything unrecognised."""

    raw_steps = payload.get("steps") if isinstance(payload, dict) else payload
    if not isinstance(raw_steps, list):
        raise TypeError("steps 必须是数组")

    steps: list[PlannedStep] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_steps, start=1):
        if not isinstance(item, dict):
            raise TypeError("每个步骤必须是对象")
        tool = str(item.get("tool", "")).strip()
        if tool not in TOOL_WHITELIST:
            raise ValueError(f"非白名单工具：{tool!r}")
        step_id = str(item.get("step_id") or f"s{index}").strip() or f"s{index}"
        if step_id in seen:
            raise ValueError(f"步骤编号重复：{step_id}")
        seen.add(step_id)

        depends = item.get("depends_on") or []
        if not isinstance(depends, list):
            raise TypeError("depends_on 必须是数组")
        parameters = item.get("parameters") or {}
        if not isinstance(parameters, dict):
            raise TypeError("parameters 必须是对象")
        parameters = {str(key): value for key, value in parameters.items()}
        if tool == "optimize_pipeline":
            allowed = {"max_trials", "n_trials", "timeout_seconds", "random_seed", "search_space",
                       "optimization_policy", "diagnose_feedback"}
            unexpected = sorted(set(parameters) - allowed)
            if unexpected:
                raise ValueError(f"optimize_pipeline 收到未映射的计划参数：{', '.join(unexpected)}")
            if "optimization_policy" in parameters and parameters["optimization_policy"] not in {
                "established", "paired_coverage", "disturbance_aware", "validation_guarded"}:
                raise ValueError("optimize_pipeline 收到未知优化策略")
            if "diagnose_feedback" in parameters and type(parameters["diagnose_feedback"]) is not bool:
                raise ValueError("diagnose_feedback 必须为布尔值")
            for key in ("max_trials", "n_trials"):
                if key in parameters:
                    value = parameters[key]
                    if type(value) is not int or not 1 <= value <= 10000:
                        raise ValueError(f"optimize_pipeline 的 {key} 必须是 1 到 10000 的整数")
            if "n_trials" in parameters:
                trials = parameters.pop("n_trials")
                if "max_trials" in parameters and parameters["max_trials"] != trials:
                    raise ValueError("optimize_pipeline 的 n_trials 与 max_trials 冲突")
                parameters["max_trials"] = trials

        steps.append(
            PlannedStep(
                step_id=step_id,
                tool=tool,
                depends_on=tuple(str(value) for value in depends),
                parameters=parameters,
                # The flag is set from the whitelist, not from the model: a model that
                # forgot it must not thereby unlock an unconfirmed export.
                requires_confirmation=tool in CONFIRMATION_REQUIRED,
            )
        )
    return steps


def _coerce_assumptions(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return []
    raw = payload.get("assumptions") or []
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if str(item).strip()][:10]
