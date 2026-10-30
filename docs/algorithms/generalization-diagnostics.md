# ProcessPilot 泛化诊断口径

## 目的与边界

本诊断解释一个已经完成的 OptimizationStudy 为什么在 held-out Test 上表现变化。它以已由 Validation 选定的 Best Trial 做只读重放；不运行 Optuna、不创建 Trial、不更新 Study，也不根据 Test 调整参数。

入口：`GET /api/v1/optimization/optuna/{study_id}/diagnostics`。

## 输出证据

诊断按与 ARX 指标相同的时间顺序评分区间输出 Train、Validation、Test（边界处会排除 ARX 最大历史长度的 guard，避免滞后特征跨分区）。

| 维度 | 真实计算 | 解释边界 |
| --- | --- | --- |
| 数据分布 | 每个输入/输出的均值、标准差、最小值、最大值和活动率 | 发现范围/活动差异，不自动证明因果 |
| 动态选段覆盖 | Best Trial 重放后的选中样本数量、最早/最晚位置和覆盖跨度 | 选段只来自 Train；不把 Validation/Test 泄漏给 D-最优选择 |
| 可辨识性 | 回归矩阵秩、参数数、条件数、持续激励阶次 | 条件数高/秩不足提示数值和激励风险，不单独判定模型无效 |
| 时滞稳定性 | 每个分区的预白化互相关峰 lag 和预白化阶次 | 峰 lag 是候选证据，不能等价为过程真实时滞一定改变 |
| 模型稳定性 | AR 多项式极点最大模和稳定性 | 检查自由仿真是否可能因递推不稳定而退化 |
| 残差 | 分区 one-step 残差白度比例 | 白度低表示仍可能存在未建模结构 |
| 预测模式差距 | 同分区 one-step 与 free-run 指标 | 识别“短期预测高、长程递推差”的误差累积现象 |

## 结论规则

API 的 `diagnostic_messages` 只在对应数值证据存在时增加提示：测试输入/输出范围超出训练的均值±0.5个标准差、有效相关（|r|≥0.1）的互相关峰 lag 跨分区相差至少 2、测试矩阵秩不足或条件数高于训练的 10 倍、测试输入完全无活动、测试残差白度低于 0.50，或 Test 的 one-step/free-run FIT 差超过 25 个百分点。

这些提示是工程诊断证据，不是唯一因果归因。若没有足以支持具体机制的附加证据，响应会明确写出“当前证据不足以唯一确定泛化变差的根因。”

## 与评价协议的关系

正式比较仍是 validation free-run FIT；最终 Test free-run FIT 只用于最终评价和诊断。Generalization Gap 统一为：

```text
best_validation_free_run_fit - best_test_free_run_fit
```

完整 FIT/R² 公式、one-step/free-run 定义与 Test 隔离规则见 [model-evaluation.md](model-evaluation.md)。
