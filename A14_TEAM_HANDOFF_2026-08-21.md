> 历史阶段文档：内容反映原编写阶段，部分待办、测试计数、数据库版本和功能状态已过时。当前状态请先读 AI_CONTEXT.md，并以 2026-10-07 整合记录和当前源码为准。

# A14 ProcessPilot 团队测试与开发交接文档

> 更新时间：2026-08-21 晚  
> 项目根目录：`E:\服外\A14`  
> 当前 Git 分支：`feat/versioned-preprocessing-pipeline`  
> 当前阶段：第三阶段“版本化预处理流水线”人工验收中  
> 交接对象：后续负责人工测试、问题复现与修改验证的组员

---

## 1. 最重要的当前状态

项目已经完成：

- 统一数据资产与真实 UUID；
- Simulation 与 Upload 统一进入 `Dataset → DatasetVersion → Profile`；
- Dashboard 去除假数据与假 ID；
- 严格 Baseline、Train/Validation/Test 隔离；
- one-step/free-run 指标审计；
- 泛化与可辨识性诊断；
- 版本化 Cleaning、Lag Compensation、Feature Selection；
- 前端健康状态真实轮询；
- S4 Cleaning 的真实前端人工验收。

当前正式 S4 数据已经形成：

```text
V0 仿真原始数据
c13979a1-206e-4a8f-8e37-a22e12f6027d
        │
        └── preprocessing.clean
            │
            ▼
V1 清洗规整数据
caee11ea-9a81-4c85-9d95-4c66b10c3473
```

V0、V1 均已成功从系统真实下载：

- `accept_S4_clean-v0.csv`
- `accept_S4_clean-v1.csv`

尚未完成的第一项工作是：

1. 比较两个 CSV 的 SHA-256；
2. 确认两者均为 1200 行、4 列；
3. 确认两者内容不同；
4. 完成 S4 Cleaning 人工验收闭环；
5. 再进入 S2 Delay 人工验收。

不要重新执行正式 S4 Cleaning。

---

## 2. 本轮用户已经完成的操作

用户已经亲自完成以下人工操作与验收：

1. 启动 Docker Desktop、后端容器和前端 Vite；
2. 验证右上角 `System Ready`；
3. 验证后端停止后前端自动显示 `Backend Offline`；
4. 验证后端恢复后前端自动恢复 `System Ready`；
5. 生成 S4 正式数据集 `accept_S4_clean`；
6. 查看 V0 数据质量诊断；
7. 发现原诊断页直接展示大段冻结区段 JSON；
8. 发现正常 15/19 点阶跃保持被误判为大量冻结；
9. 将问题交给 Codex 修复并重新验证；
10. 进入 Cleaning 页面；
11. 发现前端发送 `ds_s3_demo` 和 `V0_Original`，导致 UUID 校验失败；
12. 修复后再次执行正式 Cleaning；
13. 成功生成 V1 清洗版本；
14. 验证 Hub 中 active version 更新；
15. 验证 V0→V1 的父子关系；
16. 验证 V1 Profile 已重新计算；
17. 发现 Preview 有真实数据但无法滚动且页面大量空白；
18. 修复并验证 Preview 现在可滚动到第 100 行；
19. 发现 DAG 直接显示大段 JSON、冻结口径不一致、处理数量语义不清；
20. 修复并验证 DAG 的中文结构化展示；
21. 验证原始审计 JSON 可独立滚动并复制；
22. 验证复制成功提示为“原始审计 JSON 已复制”；
23. 验证 V1 的 `hampel`、`linear_interpolate`、`none`、`mean` 已转为中文业务文案；
24. 成功下载正式 V0 和 V1 CSV。

用户没有执行任何正式 Git 提交。

---

## 3. 项目目标与定位

比赛题目：

> 服务外包创新大赛 A14：基于 Agent 的流程工业建模数据智能优选与闭环寻优系统【和利时】

项目目标不是普通数据分析网站，而是：

```text
工业时序数据
→ 用户自然语言需求
→ Agent 生成结构化流程
→ 数据质量检查与 Cleaning
→ 动态建模区段选择
→ 输入输出时滞分析与补偿
→ 共线性分析与冗余变量处理
→ 系统辨识
→ 模型评价
→ 根据评价形成闭环寻优
→ 最优数据与模型
→ 报告与数据导出
```

必须坚持：

- 真实数据；
- 真实 UUID；
- 真实 DatasetVersion；
- 真实 ProcessingRun；
- 真实模型；
- 真实 Optuna；
- 真实指标；
- 真实错误；
- 真实报告；
- 宁可显示失败、风险高或暂无指标，也不能显示假数据。

---

## 4. 技术栈

### 前端

- Vue 3
- TypeScript
- Vite
- Vue Router
- Pinia
- Element Plus
- ECharts
- Axios

### 后端

- Python 3.11+
- FastAPI
- Pydantic
- Uvicorn

### 数据库与任务

- PostgreSQL 16
- SQLAlchemy Async
- Alembic
- Redis 7
- RQ Worker

### 工业算法

- NumPy
- D-optimal
- 预白化互相关
- Pearson / Spearman
- VIF / Condition Number
- MISO ARX
- OLS / Ridge
- Optuna

### Agent

- RuleBasedPlanner
- Pydantic Schema
- Tool whitelist
- DAG
- Compliance
- 可选 OpenAI-compatible LLM

当前：

```text
INDUSOPT_LLM_PROVIDER=none
```

目前仍使用 RuleBasedPlanner，不要在执行层未稳定前接 DeepSeek、Ollama 或其他真实 LLM。

---

## 5. 核心架构原则

```text
Agent   = 策略层
Optuna  = 数值优化层
Python 工业算法 = 执行工具层
```

不要让 LLM 自己随意调每一个数值参数。

正确结构：

```text
Agent 决定工作流与搜索策略
→ Optuna 搜索数值参数
→ 工业算法真实执行
```

现有核心算法已经是真实资产，不要随意重写：

- 质量门控 + D-optimal；
- 预白化互相关 + refinement；
- Pearson / Spearman / VIF / Condition Number；
- MISO ARX；
- OLS / Ridge；
- MAE / RMSE / R² / FIT / AIC / BIC；
- one-step / free-run；
- residual whiteness；
- stability；
- Optuna。

---

## 6. Git 历史与当前分支

Git：

```text
git version 2.55.0.windows.4
```

已完成 Checkpoint：

### 阶段1

```text
分支：fix/unified-dataset-dashboard
提交：f2f2a70 fix: unify simulation dataset lifecycle and dashboard
```

### 阶段2-A

```text
分支：fix/evaluation-baseline-generalization
提交：54dd224 feat: add strict baseline and held-out generalization evaluation
```

### 阶段2-B

```text
分支：fix/evaluation-metric-audit
提交：3a30f14 fix: audit model evaluation metrics and diagnostics
```

### 当前阶段3

```text
分支：feat/versioned-preprocessing-pipeline
```

第三阶段尚未提交最终 Checkpoint。

建议最终提交信息：

```text
feat: add immutable versioned preprocessing pipeline
```

只有 S4、S2、S5、S6 全部人工验收通过后才能提交。

---

## 7. 必须保护的用户文件

禁止删除、覆盖或自动清理：

- `docs/reference/`
- `math-modeling.zip`
- `tmp/`

禁止使用：

- `git clean`
- `git reset --hard`
- 强制 checkout 覆盖用户修改

执行以下操作前必须明确获得用户授权：

- 修改源码、配置、文档、测试；
- 安装或升级依赖；
- 数据库迁移；
- Docker build；
- Git add/commit/push/rebase/merge/reset；
- 删除数据集或文件。

---

## 8. 已完成：统一数据资产

以前存在两套系统：

```text
Upload → Dataset → DatasetVersion
Simulation → CSV / manifest → algorithms
```

现在统一为：

```text
Upload / Simulation
→ Dataset
→ DatasetVersion
→ Profile
→ Modeling
→ Optimization
→ Report
→ Export
```

Simulation 会创建：

- 真实 Dataset UUID；
- 真实 Root DatasetVersion UUID；
- 真实 DatasetProfile。

Dashboard 已删除：

- `ds_s2`
- `ds_s3`
- `ds_s4`
- 假 Baseline FIT
- 假 Optimized FIT
- 假 Improvement

Simulation 假 CSV 下载和 Cleaning 假正弦 fallback 均已删除。

---

## 9. 已完成：严格 Baseline 与 Test 隔离

每个正式 Optuna Study 前先运行 deterministic baseline。

默认：

- window = 60
- max_segments = 10
- missing_threshold = 0.20
- anomaly_threshold = 0.10
- activity_threshold = 0.05
- na = 2
- nb = 2
- nk = 0
- estimator = OLS

时序连续切分：

```text
Train      60%
Validation 20%
Test       20%
```

禁止随机 shuffle。

用途：

- Train：拟合模型；
- Validation：Optuna objective 与 Best Trial 选择；
- Test：Best Trial 固定后最终只评估一次。

禁止：

- Test 进入 Optuna；
- 根据 Test 调参数；
- 根据 Test 选择 Trial；
- 为了 Test 好看重跑。

Generalization Gap：

```text
optimized_validation_fit - optimized_test_fit
```

工程风险提示：

- ≤10个百分点：正常；
- 10～25：注意；
- >25：泛化风险高。

---

## 10. 指标口径

### One-step

每一步使用真实历史输出预测下一步，短期指标通常更高。

### Free-run

暖启动后使用模型自己的预测继续滚动，更严格反映长期动态仿真能力。

公式：

```text
R² = 1 - SSE/SST
FIT = 100 × (1 - ||y-ŷ|| / ||y-ȳ||)
```

未触发 FIT 下限时：

```text
FIT = 100 × (1 - sqrt(1-R²))
```

Free-run FIT 保留 `-100%` 下限。

---

## 11. S6 既有审计结论

曾使用：

- 1200点；
- Seed = 20260820；
- 5 trials。

结果：

| 区间 | One-step FIT / R² | Free-run FIT / R² |
|---|---|---|
| Validation | 97.16% / 0.9992 | 85.98% / 0.9803 |
| Test | 77.45% / 0.9491 | 19.83% / 0.3573 |

Generalization Gap：66.14个百分点。

真实诊断：

- Test 三个输入活动率为0；
- Train rank = 12/12；
- Test rank = 3/12；
- 最大极点模 = 0.7844，稳定；
- Test one-step 残差白度 = 0.95；
- D-optimal 覆盖训练区间约93.75%；
- Test 无可靠 delay evidence。

结论：

> S6 是弱激励与泛化风险压力测试，不是 ARX、FIT 或稳定性算法错误。

不要为了结果漂亮修改 Ground Truth 或反复调参。

---

## 12. 版本化预处理设计

UI 当前使用从0开始的显示编号：

```text
V0 Original
→ V1 Cleaning
→ V2 Lag Compensation
→ V3 Feature Selection
→ ARX
→ Optuna
```

旧文档有时写作 V1/V2/V3/V4。验收以 UUID 和 parent 为准，不以显示编号为准。

所有数据变更必须：

- 创建新不可变 CSV；
- 创建新 DatasetVersion；
- 创建新 Profile；
- 创建 ProcessingRun；
- 保存审计信息；
- 不覆盖父版本。

---

## 13. Cleaning 规则

支持：

- 时间规整；
- 重采样；
- 线性、前向、后向插值；
- Hampel；
- IQR；
- Z-score；
- 局部中值；
- clip；
- Moving Average；
- Savitzky-Golay。

Cleaning 后行数不一定减少。

例如：

```text
V0 1200行 → V1 1200行
```

这可以是正确结果。

---

## 14. Delay 与 Feature Selection 规则

### Delay

```text
Delay Analyze ≠ Lag Apply
```

Analyze：

- 只分析；
- 不创建版本。

Apply：

- 必须用户确认；
- 真正 shift 数据；
- 创建新版本。

补偿语义：

```text
u_aligned(t) = u_source(t-nk)
```

保持 y、timestamp 不移动，删除开头 `max(lag_map)` 个边界行。

### Feature Selection

```text
Collinearity Analyze ≠ Feature Apply
```

Analyze：

- Pearson；
- Spearman；
- VIF；
- Condition Number；
- 只提供建议；
- 不创建版本。

Apply：

- 必须用户确认；
- 创建新版本；
- 禁止删除 timestamp、y；
- 至少保留一个 input。

---

## 15. 阶段3自动 E2E 证据

曾完整跑通：

```text
V1 e22698fd-a59f-4589-8f70-7b8d7a0c4dbf
→ Cleaning V2 b58e29ea-db5f-40c7-a3ca-13215816dc15
→ Lag V3 a7e8632f-b7f0-47fc-ab86-0f1fab778ff7
→ Feature V4 db80f751-3f2f-479f-8d15-c07bbd16c732
```

Lag：

```text
{u1: 3, u2: 8}
1200 → 1192
```

Feature：删除 u2，4列→3列。

ARX 读取最终版本成功。

Optuna Study：

```text
8cb562b2-b391-4485-8595-d680a5fb9b83
```

---

## 16. 健康状态修复

原问题：

- 后端 ready 时前端显示 Connecting；
- 后端关闭后反而显示 System Ready；
- 初始 `isHealthy=true`；
- catch 中有 Demo fallback；
- 没有 polling。

现在状态：

- connecting
- ready
- offline

真实 ready 条件：

```text
live.status === "ok"
ready.status === "ready"
database === "connected"
queue === "connected"
```

每5秒轮询，并防止请求重叠。

已经人工验证后端停止与恢复的双向切换。

---

## 17. 当前正式 S4 数据

Dataset：

```text
accept_S4_clean
```

Dataset ID：

```text
f4c27bd2-f27f-40eb-aa61-04988f71f616
```

配置：

- Scenario：S4；
- 样本数：1200；
- Seed：9999；
- 字段：timestamp、u1、u2、y；
- 系统：MISO_ARX；
- true_na = 2；
- true_delays：u1=3、u2=8；
- noise level = 0。

实际污染：

- y 异常注入：12个，1%；
- u1 缺失注入：36个，3%；
- y 缺失注入：36个，3%；
- u1 冻结：540–620，共81点；
- y 漂移：864–1199，共336点；
- 不规则时间戳：19个；
- 重复时间戳：12个。

---

## 18. V0 正式数据

UUID：

```text
c13979a1-206e-4a8f-8e37-a22e12f6027d
```

操作：

```text
simulation_generate
```

文件：

```text
simulation/f4c27bd2-f27f-40eb-aa61-04988f71f616.csv
```

行/列：

```text
1200 / 4
```

V0 Profile：

- 质量分数：90.3718398；
- 总体缺失率：1.38%；
- 不规则采样率：5.00%；
- u1 缺失率：2.50%；
- y 缺失率：3.00%；
- y 候选异常点：84；
- 候选异常冻结：u1 540–620，共81点。

---

## 19. 冻结检测 Bug 与修复

原算法将所有连续相等且长度≥5的区段都称为“冻结”，导致：

- u1 大量15点正常阶跃保持被误报；
- u2 大量19点正常阶跃保持被误报；
- 页面直接显示数屏 JSON；
- 内部字段 `column/start_index/end_index/length` 暴露。

现在统一为：

- `constant_value_segments`：全部恒值区段，仅作审计；
- `candidate_frozen_segments`：相对于变量自身常规保持长度显著异常的候选区段。

S4 最终只识别：

```text
u1 540–620，共81点
```

界面使用“候选异常冻结段”，不直接认定仪表故障。

---

## 20. Cleaning 请求 UUID Bug 与修复

第一次人工 Cleaning 失败：

```text
REQUEST_VALIDATION_FAILED
```

前端错误发送：

```json
{
  "dataset_id": "ds_s3_demo",
  "version_id": "V0_Original"
}
```

后端要求真实 UUID，因此 Pydantic 在进入服务前拒绝。

失败请求没有产生任何：

- DatasetVersion；
- Profile；
- ProcessingRun；
- CSV；
- active version 变化。

修复后 Cleaning 页面显示真实源版本 UUID，并使用正式请求字段。

---

## 21. V1 正式 Cleaning 结果

UUID：

```text
caee11ea-9a81-4c85-9d95-4c66b10c3473
```

父版本：

```text
c13979a1-206e-4a8f-8e37-a22e12f6027d
```

操作：

```text
preprocessing.clean
```

文件：

```text
derived/f4c27bd2-f27f-40eb-aa61-04988f71f616/caee11ea-9a81-4c85-9d95-4c66b10c3473.csv
```

行/列：

```text
1200 / 4
```

参数：

- 目标采样周期：1秒；
- 插值：线性插值；
- 异常检测：Hampel 滤波；
- Hampel 窗口：5个采样点；
- 异常处理：线性插值替换；
- 重复时间戳：均值聚合；
- 平滑：未启用。

处理结果：

- 唯一变更单元格：111；
- 缺失填补：99；
- Hampel 异常替换：12，全部位于 y；
- 平滑修改：0；
- 重复时间戳处理：12行，不计入111。

99个缺失填补：

- u1：39；
- u2：12；
- y：48。

111 的定义：

```text
99 个缺失填补 + 12 个异常替换 = 111 个唯一变更单元格
```

类别无重叠。

---

## 22. V1 Profile

V1 Profile 已重新计算：

- 质量分数：95.8611111；
- 总体缺失率：0%；
- 不规则采样率：0%；
- timestamp/u1/u2/y 有效行均为1200；
- y 候选异常点：77；
- 候选异常冻结仍为 u1 540–620，共81点。

质量变化：

```text
90.37 → 95.86
```

缺失率：

```text
1.38% → 0%
```

不规则采样率：

```text
5% → 0%
```

注意：

V1 仍有77个 Profile 候选异常点，不代表 Cleaning 失败。Cleaning 使用 Hampel 替换12点，而 Profile 可能使用另一统计口径，且 S4 尾段包含漂移。禁止为了让异常数归零重复 Cleaning。

---

## 23. Preview 当前能力

数据集详情 Overview 已修复：

- 使用 active V1；
- 显示真实前100行；
- 字段为 timestamp/u1/u2/y；
- 显示 `100 / 1200行`；
- 标明仅展示前100行；
- 表头固定；
- 表格内部上下滚动；
- 可滚动到第100行；
- 自动利用页面剩余高度；
- 支持横向滚动；
- loading、empty、error 分开；
- 不把整个1200行 CSV 无限制传入浏览器。

---

## 24. DAG 当前能力

DAG 现在结构化显示 V0/V1：

### V0

- UUID；
- 父版本；
- 操作类型；
- 创建时间；
- 行列数；
- 文件路径；
- 用户请求参数；
- 场景解析后实际生效参数；
- 原始审计参数。

实际生效参数按中文表格展示：

- 异常注入；
- 缺失注入；
- 已知冻结注入；
- 已知漂移注入；
- 时间戳污染。

### V1

业务摘要已中文化：

- Hampel 滤波；
- 线性插值替换；
- 均值聚合；
- 未启用；
- 单元格、行、段、秒、采样点等单位明确。

原始审计 JSON：

- 默认折叠；
- 精确保留内部字段；
- 独立滚动；
- 支持复制；
- 成功提示明确。

原始 JSON 中仍保留历史 `mean` 和旧 warning 是正确设计，因为审计层不能改写历史记录；业务层已经转换为准确中文。

---

## 25. 当前数据库完整性

正式 S4 只读检查：

```text
DatasetVersion：2
DatasetProfile：2
ProcessingRun：1
Active Version：V1
血缘边：1
```

正式版本：

```text
V0 c13979a1-206e-4a8f-8e37-a22e12f6027d
V1 caee11ea-9a81-4c85-9d95-4c66b10c3473
```

多次 UI 和兼容层修复前后，正式 V0/V1 CSV 的 SHA-256 未被系统改写。

---

## 26. 已下载的两个 CSV

用户已经从系统真实下载：

- `accept_S4_clean-v0.csv`
- `accept_S4_clean-v1.csv`

它们不是 ChatGPT/Codex 临时生成的数据，而是系统后端保存的两个真实版本：

- V0 来源：`simulation/...csv`
- V1 来源：`derived/.../version_uuid.csv`

下载接口：

```text
GET /api/v1/datasets/{dataset_id}/download?version_id={version_id}
```

下一位测试人员应首先比较这两个文件。

### 建议检查

1. 两个文件均为1200行、4列；
2. 列为 timestamp/u1/u2/y；
3. SHA-256 不同；
4. V1 不再包含缺失值；
5. V1 timestamp 已规整为1秒；
6. V0、V1 内容不同；
7. V0 文件仍保持原始污染；
8. V1 没有错误删除 u1 540–620 冻结区段；
9. V1 没有错误移除 y 尾段漂移。

### PowerShell 建议

不要猜下载目录。先确认两个文件的绝对路径，再运行：

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath "<V0绝对路径>"
Get-FileHash -Algorithm SHA256 -LiteralPath "<V1绝对路径>"
```

也可以把两个文件上传到普通 Chat 中，让 Chat 只读分析行列数、缺失值与差异。

---

## 27. 临时测试数据集

Codex 为测试 Cleaning API 创建过：

```text
contract-cleaning-temp-20260821
```

它不属于正式 S4，目前尚未删除。

后续如需清理：

1. 先确认临时 Dataset 的真实 UUID；
2. 精确确认目标名称；
3. 用户明确授权；
4. 仅删除该临时数据集；
5. 不得误删 `accept_S4_clean`；
6. 不得使用批量模糊清理。

---

## 28. 当前测试状态

已经运行：

- 后端纯算法 pytest：5 passed；
- Ruff：通过；
- 前端完整 Vitest：6 files / 27 tests passed；
- `npm.cmd run build`：通过；
- `git diff --check`：通过，仅有既有 LF/CRLF 提示；
- Docker rebuild：成功；
- backend/worker/postgres/redis：均 Up；
- Health：ready/connected/connected；
- 正式 Preview：100行，字段正确。

未完整执行：

- 部分后端路由测试。

原因：

- Windows Python 缺 FastAPI/aiosqlite；
- 现有 `.venv` 为 Linux 格式；
- 当前没有可用 WSL；
- Docker 镜像没有 pytest；
- 遵守限制，未安装额外依赖。

相关测试代码已经补充，但不能声称所有后端 pytest 已通过。

现有前端 build 有 >500KB chunk 警告，属于既存问题，不阻塞当前功能验收。

---

## 29. 当前 Git 状态

最近一次完整统计约为：

```text
25 files changed, 2373 insertions(+), 160 deletions(-)
```

之后还有少量前端展示修改，实际统计可能略有变化。

当前已知状态：

```text
M CHANGELOG.md
M backend/algorithms/cleaning/pipeline.py
M backend/algorithms/cleaning/quality.py
M backend/app/api/routes.py
M backend/app/schemas/datasets.py
M backend/app/schemas/preprocessing.py
M backend/app/services/cleaning_service.py
M backend/app/services/dataset_service.py
M backend/tests/test_cleaning_api.py
M backend/tests/test_datasets.py
M backend/tests/test_simulation_dataset_lifecycle.py
M docs/PROJECT_HANDOFF_ANALYSIS.md
M frontend/src/App.vue
M frontend/src/api/preprocessing.ts
M frontend/src/components/AppHeader.vue
M frontend/src/layouts/DefaultLayout.vue
M frontend/src/stores/systemStore.ts
M frontend/src/types/api.ts
M frontend/src/views/CleaningView.vue
M frontend/src/views/CollinearityView.vue
M frontend/src/views/DashboardView.vue
M frontend/src/views/DatasetDetailView.vue
M frontend/src/views/DelayView.vue
M frontend/src/views/SettingsView.vue
M frontend/tests/unit/store.spec.ts
?? backend/app/services/versioned_preprocessing_service.py
?? backend/tests/test_quality_profile_freeze_detection.py
?? backend/tests/test_versioned_preprocessing.py
?? docs/architecture/dataset-versioning.md
?? docs/reference/
?? frontend/tests/unit/cleaning-view-contract.spec.ts
?? frontend/tests/unit/dataset-detail-freeze-segments.spec.ts
?? frontend/tests/unit/dataset-detail-version-preview.spec.ts
?? frontend/tests/unit/system-status-components.spec.ts
?? math-modeling.zip
?? tmp/
```

没有执行：

- git add
- git commit
- git push
- git reset
- git clean

工作区虽大，但修改来源清楚：第三阶段、健康状态修复以及人工验收中发现的问题。

---

## 30. 当前运行方式

### Docker

打开 Docker Desktop，然后：

```powershell
cd "E:\服外\A14"
docker compose up -d --build
docker compose ps
```

当前没有新增迁移。

Migration head：

```text
0003_optimization_and_memory
```

### 前端

```powershell
cd "E:\服外\A14\frontend"
npm.cmd run dev
```

浏览器地址通常：

- `http://localhost:5173`
- 如果端口占用则为 `http://localhost:5174`

### 后端

- Swagger：`http://localhost:18000/docs`
- Health：`http://localhost:18000/api/v1/health/ready`

正常：

```text
status = ready
database = connected
queue = connected
```

如果当前容器和 Vite 仍在运行，不要无意义重复 build。

---

## 31. 后续人工验收固定顺序

```text
S4 → Cleaning
S2 → Delay
S5 → Collinearity
S6 → ARX + Optuna
```

### S4 当前完成度

| 检查项 | 状态 |
|---|---|
| Generate V0 | 通过 |
| V0 Profile | 通过 |
| Cleaning 请求使用真实 UUID | 通过 |
| Cleaning 创建 V1 | 通过 |
| 新 UUID | 通过 |
| parent 正确 | 通过 |
| active version 更新 | 通过 |
| V1 Profile | 通过 |
| ProcessingRun | 通过 |
| Preview | 通过 |
| DAG | 通过 |
| V0 下载 | 通过 |
| V1 下载 | 通过 |
| V0/V1 文件差异 | 待最终核验 |

---

## 32. S2 Delay 下一步测试方案

只有 S4 文件差异验证通过后再开始。

生成：

```text
Scenario：S2 多输入不同滞后
N：1200
Seed：9002
Name：accept_S2_delay
```

测试要求：

1. Generate 创建真实 Dataset 与 Root Version；
2. 记录初始 Version 数量；
3. 执行 Delay Analyze；
4. Analyze 后 Version 数量必须不变；
5. 查看 candidate delay、refined delay 与证据；
6. Ground Truth 预期 u1=3、u2=8，但验收以实际算法证据为准；
7. 只有证据可靠时才允许 Apply；
8. Apply 必须要求用户确认；
9. Apply 后创建新 UUID；
10. parent 指向 Analyze 的源版本；
11. 如果最大 lag 为8，通常 1200→1192，但以真实结果为准；
12. V0 仍可下载；
13. 新版本可下载；
14. Profile 重新计算；
15. ProcessingRun 存在；
16. 如果证据不足，禁止强行 Apply。

重点检查：

- Analyze 是否被错误描述为“已完成补偿”；
- Apply 是否可能在未确认时自动执行；
- 请求是否仍存在 Demo ID；
- active version 是否正确传播；
- 边界行删除是否与最大 lag 一致。

---

## 33. S5 Collinearity 测试方案

```text
Scenario：S5 高共线性输入
N：1200
Seed：9005
Name：accept_S5_collinearity
```

Analyze：

- Pearson；
- Spearman；
- VIF；
- Condition Number。

测试要求：

1. Analyze 不创建版本；
2. 建议必须带证据；
3. 用户确认后才 Feature Apply；
4. Apply 创建新 UUID；
5. parent 正确；
6. 列数减少；
7. timestamp/y 保留；
8. 至少保留一个 input；
9. 原版本仍可下载；
10. 新版本可下载；
11. Profile 与 ProcessingRun 正确。

---

## 34. S6 ARX + Optuna 测试方案

```text
Scenario：S6 异构激励压力测试
N：1200
Seed：9006
Name：accept_S6_pipeline
```

基础 ARX：

```text
na = 2
nb = 2
nk = 0
estimator = OLS
```

Optuna：

```text
Trials = 5
```

流程：

```text
Generate
→ ARX
→ Baseline
→ Optuna
→ Best Trial
→ Final held-out Test
→ Dashboard
```

Dashboard 新 Study 应显示：

- Baseline Validation FIT；
- Optimized Validation FIT；
- Optimized Test FIT；
- Test one-step FIT；
- Test one-step R²；
- Test free-run FIT/R²；
- Improvement；
- Generalization Gap；
- 工程风险提示。

S6 出现泛化风险高不是失败，不要为了结果漂亮重跑。

---

## 35. 发现 Bug 后的修改原则

如果人工测试发现问题：

1. 先保存截图；
2. 记录 Dataset ID、Version ID、Study ID；
3. 记录页面参数；
4. 获取真实 HTTP 状态码与字段级错误；
5. 检查失败是否产生半成品；
6. 先写失败测试；
7. 做最小范围修复；
8. 不改变现有核心算法；
9. 不硬编码数据集名、Seed、UUID、列名或期望结果；
10. 不加入 Mock 或 fallback；
11. 错误信息必须可操作；
12. 修复后运行相关后端/前端测试；
13. 运行完整前端 Vitest；
14. 运行 build；
15. 运行 `git diff --check`；
16. 重新检查正式数据版本数是否变化；
17. 不执行 Git 提交，除非用户明确授权。

### Bug 报告模板

```markdown
## 问题

页面：
数据集：
Dataset ID：
Source Version ID：
操作参数：

### 预期行为

### 实际行为

### 错误码与字段详情

### 是否产生新版本/文件/ProcessingRun

### 截图

### 复现步骤

### 建议测试
```

---

## 36. 第三阶段最终通过标准

必须全部确认：

### S4

```text
Generate → V0 → Cleaning → V1
```

### S2

```text
Generate
→ Delay Analyze
→ Version 不变
→ 用户确认
→ Lag Apply
→ 新 Version
```

### S5

```text
Generate
→ Collinearity Analyze
→ Version 不变
→ 用户确认
→ Feature Apply
→ 新 Version
```

### S6

```text
Generate
→ ARX
→ Baseline
→ Optuna
→ Final Test
→ Dashboard
```

共同要求：

- 真实 UUID；
- parent 正确；
- 源版本不覆盖；
- 各版本可下载；
- Profile 重新计算；
- ProcessingRun 存在；
- 错误真实；
- 无 Mock；
- Test 不参与调参。

---

## 37. 第三阶段完成后

全部验收通过后：

1. 运行最终测试；
2. 检查 `git status`；
3. 检查 `git diff`；
4. 保护用户文件；
5. 创建 Checkpoint：

```text
feat: add immutable versioned preprocessing pipeline
```

之后才创建：

```text
feat/agent-execution-workflow
```

---

## 38. 下一开发阶段：Agent 完整执行工作流

目标：

```text
User
→ Planner
→ Structured Plan
→ Schema
→ Whitelist
→ DAG
→ Execution Session
→ Profile
→ Clean → V2
→ Delay Analyze
→ WAITING_CONFIRMATION
→ Lag Apply → V3
→ Collinearity Analyze
→ WAITING_CONFIRMATION
→ Feature Apply → V4
→ ARX(V4)
→ Baseline + Optuna(V4)
→ Report
→ Export
```

必须实现 `current_version_id` 传播，禁止 ARX/Optuna 重新读取 Root Version。

Confirm 必须真正续跑，而不是只记录 approved/rejected。

需要 Execution Session、Step 状态、Workflow 状态与幂等性。

这一轮仍使用 RuleBasedPlanner，不接真实 LLM。

---

## 39. 后续开发顺序

```text
阶段4 Agent 完整执行工作流
→ 阶段5 接真实 LLM
→ 阶段6 Agent 策略层 + Optuna 数值反馈闭环
→ 阶段7 泛化/可辨识性诊断 UI
→ 阶段8 HTML/PDF 专家报告
→ 阶段9 公开真实工业数据验证
→ 阶段10 完整测试、答辩演示、参赛材料
```

---

## 40. 当前禁止事项

近期禁止：

- 重写 D-optimal；
- 重写 Delay 数学算法；
- 重写 VIF；
- 重写 ARX；
- 删除 Optuna；
- 为堆功能加入 XGBoost/LSTM；
- 根据 Test 调参；
- 修改 Ground Truth 让结果变漂亮；
- 执行层未稳定就接 LLM；
- 大规模 UI 重构；
- 再次执行正式 S4 Cleaning；
- 未核对 UUID 就删除临时数据集。

---

## 41. 组员接手后的第一天建议

### 第一步

只读核验两个下载 CSV：

- 行列数；
- 列名；
- SHA-256；
- 缺失值；
- timestamp 间隔；
- V0/V1 差异。

### 第二步

确认 S4 完整验收结论并保存结果。

### 第三步

检查：

```text
docker compose ps
health/ready
git status --short
```

### 第四步

开始 S2：

```text
accept_S2_delay
N=1200
Seed=9002
```

先 Generate，再 Delay Analyze。不要直接 Apply。

---

## 42. 当前安全暂停点

当前状态：

- Docker 正常；
- System Ready；
- Vite 正常；
- V0/V1 已生成；
- Profile、Preview、DAG 已通过；
- 两个 CSV 已下载；
- 没有任务运行中；
- 没有迁移；
- 没有 Optuna 运行；
- Git 状态已知；
- 没有 Git 写操作。

当前是：

> 🟢 适合休息点

下一步从比较 `accept_S4_clean-v0.csv` 与 `accept_S4_clean-v1.csv` 开始。

