> 历史阶段文档：内容反映原编写阶段，部分待办、测试计数、数据库版本和功能状态已过时。当前状态请先读 AI_CONTEXT.md，并以 2026-10-07 整合记录和当前源码为准。

# A14 IndusOpt / ProcessPilot 无损开发交接

> 交接日期：2026-08-25（Asia/Shanghai）
>
> 当前证据快照：2026-08-25 10:36 CST
>
> 交接范围：从接手基线 `e7cc8cd` 开始的 S2/S5/S6 验收与修复、前端 UI 收敛、Agent 运行时 LLM 接入及项目交接
>
> 安全说明：本文不包含、回显或提交任何真实 API Key、密码或个人敏感信息

## 1. 交接结论与口径

本轮功能开发已经通过 PR #3、#4、#5 合并到团队集成分支 `feat/versioned-preprocessing-pipeline`；功能合并基线为 `d26903f`。交接文档通过 PR #6 合并，当前集成分支提交为 `2ca32ee`。没有修改或推送 `main`。

本轮可以认定为“负责的代码开发与指定验收已完成”，但不能认定整个项目所有交付工作都已结束。Docker Compose 首次实机闭环、公开数据集外部验证、S4 下载文件最终差异核验、竞赛演示录屏和成员身份材料仍未完成。

本文采用以下证据优先级：

1. 当前 Git 提交与源码；
2. GitHub PR 元数据；
3. 2026-08-22 验收 JSON、截图与报告；
4. 当日实际执行的自动化测试输出；
5. 历史文档快照。

不同日期的测试数量和运行环境不能合并成“一次测试”。本文会分别列出历史失败、修复后结果和最新复测结果。

## 2. 本次开发目标

1. 按交接要求完成 S2 时滞、S5 共线性、S6 ARX + Optuna 的真实验收，不用 Mock，不伪造漂亮结果。
2. 修复阻断验收的最小问题，同时保留人工确认、不可变版本、Test 不调参和真实错误码等安全边界。
3. 整理前端表单、Agent 工作台、侧边栏与响应式布局，解决错位、异常断行、溢出和滚动遮挡。
4. 将原先仅由部署环境控制的 LLM 接入改为可在系统设置页运行时配置，并确保核心算法不依赖外部 LLM。
5. 修复 Agent 前端 30 秒误超时、报告血缘和测试基础设施问题。
6. 形成可供负责人继续审查、部署和向 `main` 集成的无损交接证据。

## 3. Git 分支、PR 与提交

### 3.1 分支边界

- 集成分支：`feat/versioned-preprocessing-pipeline`
- 禁止直接修改的分支：`main`
- 本文无损修订来源分支：`docs/lossless-handoff-update`
- 本文无损修订基线：`2ca32ee`
- 本文无损修订 PR：[GitHub #7](https://github.com/fu-huaige/service-outsource/pull/7)

### 3.2 Pull Request 状态

| PR | Head | Base | 状态 | 提交/合并提交 | 结论 |
| --- | --- | --- | --- | --- | --- |
| [#1](https://github.com/fu-huaige/service-outsource/pull/1) | `test/s6-pipeline-acceptance` | `feat/versioned-preprocessing-pipeline` | Open | `d720757` | S6 修复原始 PR；核心内容已由 `39fa648` 汇总进 PR #3，不应重复合并 |
| [#2](https://github.com/fu-huaige/service-outsource/pull/2) | `test/s2-delay-acceptance` | `feat/versioned-preprocessing-pipeline` | Open | `4628a2d` | S2 修复原始 PR；核心内容已由 `39fa648` 汇总进 PR #3，不应重复合并 |
| [#3](https://github.com/fu-huaige/service-outsource/pull/3) | `test/ui-form-layout-acceptance` | `feat/versioned-preprocessing-pipeline` | Merged | merge `881e55e` | 前端整体优化 + S2/S6 汇总修复 + 报告血缘 |
| [#4](https://github.com/fu-huaige/service-outsource/pull/4) | `test/sidebar-toggle-alignment` | `feat/versioned-preprocessing-pipeline` | Merged | merge `1bdca1f` | 折叠侧边栏顶部图标对齐 |
| [#5](https://github.com/fu-huaige/service-outsource/pull/5) | `test/agent-runtime-settings` | `feat/versioned-preprocessing-pipeline` | Merged | merge `d26903f` | Agent 运行时 LLM 配置、真实连接测试和超时修复 |
| [#6](https://github.com/fu-huaige/service-outsource/pull/6) | `docs/project-handoff-2026-08-25` | `feat/versioned-preprocessing-pipeline` | Merged | merge `2ca32ee` | 第一版增量交接文档 |
| [#7](https://github.com/fu-huaige/service-outsource/pull/7) | `docs/lossless-handoff-update` | `feat/versioned-preprocessing-pipeline` | 本次修订，最终状态见 GitHub | `00df8c5` 起 | 无损开发交接扩写与证据对账 |

### 3.3 开发提交顺序

| Commit | 内容 | 是否进入集成分支 |
| --- | --- | --- |
| `4628a2d` | S2 候选峰细化范围修复 | 未单独合并；由 `39fa648` 重现并汇总 |
| `d720757` | S6 基线回退、测试与工程门禁修复 | 未单独合并；由 `39fa648` 重现并汇总 |
| `55656f6` | 参数表单标签与输入控件对齐 | 是，PR #3 |
| `7cba17c` | Agent 工作台响应式布局 | 是，PR #3 |
| `435b2d7` | 全站工作台视觉和交互收敛 | 是，PR #3 |
| `6b90b73` | Cleaning 源版本说明排版 | 是，PR #3 |
| `39fa648` | 汇总 S2/S6、报告血缘、测试和部署修复 | 是，PR #3 |
| `298803c` | 折叠侧边栏顶部图标居中 | 是，PR #4 |
| `e3992c1` | Agent 运行时 LLM 配置 | 是，PR #5 |
| `ee5c36b` | 第一版项目交接文档 | 是，PR #6 |

## 4. 修改前后行为

| 范围 | 修改前 | 修改后 |
| --- | --- | --- |
| S2 时滞细化 | 预白化候选峰只检查 `±1`，冻结场景中 `u1` 得到 4 而真值为 3 | 检查范围扩为 `±2`，seed 9002 精确恢复 `u1=3、u2=8` |
| S2 安全门 | 未确认 Apply 已能拒绝，但算法证据不足，不能继续 | 仍返回 HTTP 400 / `CONFIRMATION_REQUIRED`；因 `u2` 仍不确定，按规则不创建派生版本 |
| S6 Optuna 基线 | D-最优选段使默认 OLS 设计矩阵秩亏后，Study 直接失败，Optuna 不启动 | 仅遇到 `DESIGN_MATRIX_RANK_DEFICIENT` 时用 Ridge `alpha=0.1` 重试并记录原因，其他错误仍真实失败 |
| S6 最终评价 | 没有 Study、最佳 trial、最终 Test 或 Dashboard 行 | 5/5 trials 完成，最终验证/测试 free-run FIT 为 90.27%/88.35%，Dashboard 有结果 |
| 报告字段 | 模板读取旧字段 `frozen_segment_count`，导致报告占位符未解析 | 改读 `constant_value_segment_count`，清洗派生版本可生成完全解析报告 |
| 报告血缘 | 只匹配部分参数中的版本，派生版本可能找不到对应 ProcessingRun | 同时识别 `derived_version_id` 和 `result_version_id` |
| API 合约测试 | 一项测试隐式连接本机 PostgreSQL，环境缺失时失败 | 测试使用隔离 SQLite 数据库，不依赖外部 PostgreSQL |
| UUID 测试 | 字符串 UUID 直接传 SQLAlchemy UUID 主键查询，触发 `.hex` 错误 | 显式转为 `UUID` 后查询 |
| Playwright 启动 | Preview 可能监听 `::1`，测试固定等待 `127.0.0.1` 而超时 | 显式绑定 `127.0.0.1`，支持本机 Chrome 和后端虚拟环境 |
| 前端参数表单 | 标签宽度和控件宽度不一致，长中文容易出现第一行很长、第二行一个字 | Cleaning、Delay、Collinearity、ARX、Optuna 等页统一标签栅格和控件宽度 |
| Cleaning 源版本说明 | “源数据版本（本次清洗输入）”及两段说明断行杂乱 | 标签和两句说明按一行/稳定断行布局，输入区与下方参数区分层 |
| Agent 工作台 | 版本框与任务框边缘相连，示例指令在窄屏形成过窄竖条并横向溢出 | 字段上下对齐，任务框收敛宽度，示例卡片响应式排列，长文本可换行 |
| 侧边栏 | 展开两组菜单后高度超过视口，底部项目被遮挡；折叠顶部图标中心线偏移 | 菜单区独立纵向滚动；折叠切换图标与导航图标共享中心线 |
| 页面移动 | 到顶部/底部没有产品化反馈 | 加入克制的顶部/底部回弹，支持滚轮、触控板和触摸，并尊重 reduced-motion |
| 系统设置 LLM | 页面预置演示 Key，保存按钮只显示假成功；实际 Provider 只能靠后端环境变量 | 页面读取真实后端状态，可保存/清除/恢复/测试 Provider 配置；不再保留演示 Key |
| LLM 密钥 | 前端字段可能让人误以为浏览器会持久保存 | Key 只在 PUT 时发给后端进程内存；GET 仅返回 `has_api_key`，校验错误也脱敏 |
| Agent Provider | Agent 与报告各自从部署环境构建 Provider | 两者共用当前有效运行时/环境 Provider |
| Agent 请求超时 | 通用 Axios 30 秒超时；真实模型约 33.52 秒完成时，页面先报 `timeout of 30000ms exceeded` | `/copilot/chat` 单独使用 120 秒前端超时 |
| LLM 不可用 | 已有规则回退，但用户无法在页面判断或测试真实配置 | 新增真实连接测试；失败仍回退 `RuleBasedPlanner`，核心算法保持可用 |

## 5. 是否改过核心算法

结论：**改过两处与验收直接相关的核心策略，但没有改 ARX 数学定义、D-最优准则或 Test 隔离协议。**

1. `backend/algorithms/identifiability/delay.py`
   - `_widen(..., radius=1)` 改为 `radius=2`。
   - 影响：候选时滞周围验证范围扩大两个采样点。
   - 证据：冻结 S2 场景由 `u1=4` 修复为 `u1=3`，`u2=8` 保持一致。

2. `backend/app/services/optimization_service.py`
   - 正式基线仍先运行 OLS。
   - 只有错误码精确为 `DESIGN_MATRIX_RANK_DEFICIENT` 时，才确定性回退 Ridge `alpha=0.1`。
   - 回退 estimator、alpha 和原因写入 provenance；其他错误不吞掉、不泛化回退。

未改变的核心口径：

- 离散时间 MISO ARX 方程和参数定义；
- 时间顺序 Train/Validation/Test 分区；
- Optuna 只用 Validation 调参，Test 只作最终 held-out 评价；
- 主指标为 free-run FIT，一步预测只作诊断；
- Fisher 信息与 D-最优 `log det` 优选准则；
- 高影响 Apply 需要人工确认；
- 原始版本不可覆盖。

## 6. 完整文件改动

以下清单是 `e7cc8cd..d26903f` 的完整功能差异，共 52 个文件；交接文档本身另计。

### 6.1 文档与部署

| 文件 | 修改内容 |
| --- | --- |
| `README.md` | 补充运行时 LLM 配置安全边界、恢复环境配置和 Docker 镜像源说明 |
| `backend/Dockerfile` | 新增 `PIP_INDEX_URL` build arg，并用于 pip 安装 |
| `docker-compose.yml` | backend/worker 构建透传 `PIP_INDEX_URL` |

### 6.2 后端算法、API 与服务

| 文件 | 修改内容 |
| --- | --- |
| `backend/algorithms/identifiability/delay.py` | S2 候选峰细化半径从 1 改为 2 |
| `backend/app/api/routes.py` | 新增 Agent 配置 GET/PUT/DELETE 与连接测试 POST 路由 |
| `backend/app/core/db.py` | 修正 Redis 返回类型，解决类型检查问题；无数据库结构变化 |
| `backend/app/main.py` | 校验错误响应对 `api_key/password/secret/access_token` 输入脱敏 |
| `backend/app/schemas/system.py` | 新增运行时 LLM 配置、响应和连接测试 Schema；校验 URL、Provider、超时和 Key 清除冲突 |
| `backend/app/services/agent_service.py` | Agent 改用统一的有效 Provider，而非只读部署环境变量 |
| `backend/app/services/generalization_diagnostics_service.py` | `artifact_root` 类型修正为 `Path` |
| `backend/app/services/llm_runtime_config_service.py` | 新增进程内配置、密钥保留/清除、恢复环境配置、Provider 构建和真实连接测试 |
| `backend/app/services/optimization_service.py` | S6 OLS 秩亏时受限 Ridge 回退并记录 provenance |
| `backend/app/services/report_service.py` | 统一运行时 Provider；修复恒值段字段和派生版本运行血缘匹配 |
| `backend/app/services/versioned_preprocessing_service.py` | 将 CSV 解析返回类型收紧为 `ParsedCsv` |
| `backend/openapi.json` | 按新增系统接口与 Schema 重新生成 OpenAPI 3.1 契约 |

### 6.3 后端测试

| 文件 | 修改内容 |
| --- | --- |
| `backend/tests/test_api_contract.py` | 仿真契约测试改用隔离 SQLite，移除外部 PostgreSQL 偶然依赖 |
| `backend/tests/test_cleaning_api.py` | 修复 SQLAlchemy UUID 查询类型 |
| `backend/tests/test_delay_collinearity.py` | 新增 seed 9002 精确恢复 `3/8` 的冻结 S2 回归 |
| `backend/tests/test_llm_runtime_config.py` | 新增配置读写、密钥不回显、恢复、连接测试、报告共享 Provider 和脱敏测试 |
| `backend/tests/test_optimization.py` | 新增 S6 OLS 秩亏只回退 Ridge 的回归测试 |
| `backend/tests/test_reporting.py` | 新增清洗派生版本报告完全解析和血缘测试 |

### 6.4 前端基础、接口与组件

| 文件 | 修改内容 |
| --- | --- |
| `frontend/e2e/closed-loop.spec.ts` | 适配更新后的页面文案/交互 |
| `frontend/e2e/ui-polish.spec.ts` | 新增品牌、布局和 UI 收敛浏览器回归 |
| `frontend/package-lock.json` | 更新间接依赖，消除当时 npm audit 高危项 |
| `frontend/playwright.config.ts` | 固定本机 host、浏览器与后端启动路径 |
| `frontend/src/api/agentSettings.ts` | 新增 Agent 配置 CRUD 与连接测试客户端 |
| `frontend/src/api/copilot.ts` | Agent 规划请求单独改为 120 秒超时 |
| `frontend/src/assets/main.css` | 统一视觉层级、表单栅格、响应式规则、侧栏/Agent 样式和 reduced-motion |
| `frontend/src/components/AppHeader.vue` | 保留 `IndusOpt 工模智优` 品牌并整理当前数据与状态布局 |
| `frontend/src/components/AppSidebar.vue` | 菜单滚动、折叠布局和顶部切换图标居中 |
| `frontend/src/components/StateView.vue` | 状态展示样式与页面层级适配 |
| `frontend/src/layouts/DefaultLayout.vue` | 顶部/底部回弹、滚轮/触摸处理和可访问性降级 |
| `frontend/src/router/index.ts` | 页面元信息/标题与新版工作台结构适配 |
| `frontend/src/types/api.ts` | 新增 Agent LLM 配置与连接响应类型 |

### 6.5 前端业务视图

| 文件 | 修改内容 |
| --- | --- |
| `frontend/src/views/ARXModelingView.vue` | ARX 参数标签和 `u1` 阶数等控件对齐 |
| `frontend/src/views/BenchmarkView.vue` | 页面标题、卡片和参数布局统一 |
| `frontend/src/views/CleaningView.vue` | 源版本标签/说明重排，清洗算法、Hampel 等长标签对齐 |
| `frontend/src/views/CollinearityView.vue` | 共线性参数和结果区域栅格统一 |
| `frontend/src/views/CopilotView.vue` | 重做 Agent 字段、示例指令、按钮、结果区和窄屏布局 |
| `frontend/src/views/DashboardView.vue` | 工作台首页信息层级、状态与卡片重构 |
| `frontend/src/views/DatasetDetailView.vue` | 详情页头、预览和版本区域视觉统一 |
| `frontend/src/views/DatasetsView.vue` | 数据资产列表、操作区与空/错状态统一 |
| `frontend/src/views/DelayView.vue` | 时滞页标签、输入框和结果区域对齐 |
| `frontend/src/views/DeliverablesView.vue` | 交付页面标题与卡片布局统一 |
| `frontend/src/views/OptunaView.vue` | 寻优参数表单和结果布局统一 |
| `frontend/src/views/SegmentationView.vue` | 动态区间参数和操作区对齐 |
| `frontend/src/views/SettingsView.vue` | 删除演示 Key/假保存，接入真实运行时 LLM 配置和连接测试 |
| `frontend/src/views/SimulationView.vue` | 仿真参数表单与页面层级统一 |

### 6.6 前端测试

| 文件 | 修改内容 |
| --- | --- |
| `frontend/tests/unit/cleaning-view-contract.spec.ts` | 固化 Cleaning 真实 UUID、说明排版和错误行为 |
| `frontend/tests/unit/copilot-api.spec.ts` | 固化 Agent 120 秒请求超时 |
| `frontend/tests/unit/default-layout-bounce.spec.ts` | 覆盖顶部/底部回弹与 reduced-motion |
| `frontend/tests/unit/system-status-components.spec.ts` | 更新品牌、状态、设置页和 API 配置交互测试 |

### 6.7 本轮文档文件

| 文件 | 状态 |
| --- | --- |
| `A14_PROJECT_HANDOFF_2026-08-25.md` | PR #6 新建；PR #7 完成无损扩写 |

## 7. Agent / LLM 改动

### 7.1 规划与执行边界

- LLM 只负责提出计划和生成受约束的报告叙述。
- 计划必须通过与规则计划相同的白名单和合规校验。
- 真正算法仍由后端确定性服务执行。
- Provider 未配置、连接失败、输出非法或合规失败时，回退 `RuleBasedPlanner`。
- Cleaning、Delay、Collinearity、ARX、Optuna 不依赖 LLM，离线仍可运行。

### 7.2 运行时配置

- 配置来源优先级：页面运行时覆盖 > 部署环境变量。
- 运行时配置只保存在当前 Python 进程内存。
- 后端重启或调用 DELETE 后恢复部署环境配置。
- API Key 不进入浏览器存储、不写数据库、不回显、不提交 Git。
- 当前没有管理员登录、RBAC、SSO 或加密密钥仓库，因此设置页只适合可信本地/内网。

### 7.3 已验证的真实模型行为

- Provider：DeepSeek OpenAI-compatible 服务。
- 模型：`deepseek-v4-flash`。
- 历史真实连接测试：成功，约 1.98 秒。
- 历史完整 Agent 规划：HTTP 200，约 33.52 秒。
- 返回：`plan_source=llm`，12 步计划，通过合规校验。
- 未提供 Dataset Version 时只生成计划，不执行算法，结论要求先指定数据版本。

### 7.4 真实失败与修复

1. 设置页曾出现“接口不存在”：当时页面调用的 Agent 配置路由尚未由当前运行后端提供；最终代码补齐四个路由并重新生成 OpenAPI。
2. 早期模型/地址配置的连接测试失败：页面原先要求用户自行猜 Provider、地址和模型；最终选择 DeepSeek 时自动填官方地址和默认模型，仍允许修改。
3. Agent 工作台曾显示 `timeout of 30000ms exceeded`：后端模型仍在处理，前端 30 秒先超时；最终仅对规划请求改为 120 秒。
4. 本文修订时没有再次调用真实模型，以避免无必要的外部请求和计费；只读取了不回显密钥的配置状态。

## 8. API、数据库与环境变量变化

### 8.1 API

| Method | 路径 | 变化 |
| --- | --- | --- |
| GET | `/api/v1/system/agent-config` | 返回有效配置来源、Provider、地址、模型、超时和 `has_api_key`；不返回 Key |
| PUT | `/api/v1/system/agent-config` | 应用进程内配置，可保留、替换或清除 Key |
| DELETE | `/api/v1/system/agent-config` | 清除运行时覆盖，恢复部署环境配置 |
| POST | `/api/v1/system/agent-config/test` | 向有效 Provider 发送最小真实 completion；失败返回 502 / `LLM_CONNECTION_FAILED` |
| POST | `/api/v1/copilot/chat` | 后端接口未改；前端调用超时由通用 30 秒改为该接口 120 秒 |
| POST | `/api/v1/reports/generate` | 路径未改；修复派生版本血缘匹配和旧字段占位符 |

`backend/openapi.json` 已更新；2026-08-25 使用 `jq empty` 再次验证 JSON 语法通过。

### 8.2 数据库

- 本批开发没有新增 Alembic migration，也没有修改数据库表结构。
- 当前 Schema 版本仍为 `0003_optimization_and_memory`，单一 head。
- `backend/app/core/db.py` 的改动只是 Redis 客户端类型修正。
- Agent 运行时 LLM 配置不写数据库。
- Agent 正常调用仍会按既有设计写 `ProcessingRun` 和 `OperationLog`。

### 8.3 环境变量和构建参数

| 名称 | 本批变化 | 说明 |
| --- | --- | --- |
| `INDUSOPT_LLM_PROVIDER` | 既有 | 部署 Provider；`none` 时使用规则路径 |
| `INDUSOPT_LLM_BASE_URL` | 既有 | OpenAI-compatible 基址 |
| `INDUSOPT_LLM_MODEL` | 既有 | 模型名 |
| `INDUSOPT_LLM_API_KEY` | 既有 | 部署密钥；未写入仓库 |
| `INDUSOPT_LLM_TIMEOUT_SECONDS` | 既有后端配置 | 部署调用超时；页面运行时配置可覆盖 |
| `INDUSOPT_BACKGROUND_OPTIMIZATION` | 既有 | 控制 RQ 后台寻优；关闭时同步执行 |
| `PIP_INDEX_URL` | 本批新增 Docker build arg | backend 和 worker 构建时指定 PyPI 兼容镜像 |

未新增 `.env` 文件，未提交任何真实 Key。

## 9. 执行过的测试与真实结果

### 9.1 初次验收：发现失败，未掩盖

| 检查 | 真实结果 | 后续处理 |
| --- | --- | --- |
| S2 人工验收 | 部分通过；`u1=4`、`u2=8`，u2 不确定；未确认 Apply 正确拒绝 | 修改细化半径后复测 |
| S5 人工验收 | 通过 | 无核心代码修改 |
| S6 人工验收 | 失败；基线 OLS 秩亏，HTTP 400，Study 未创建 | 增加受限 Ridge 回退后复测 |
| 后端 S2/S5/S6 定向测试 | 51 passed | 通过 |
| 后端全量 | 257 passed、3 failed、2 skipped | 修复外部 DB 偶然依赖、UUID 和报告字段 |
| Ruff | 通过 | 保持 |
| Mypy（Python 3.11 目标） | 24 errors / 4 files | 修复类型问题 |
| 前端 Vitest | 30/30 passed | 通过 |
| `vue-tsc --noEmit` | 通过 | 通过 |
| Vite build | 通过 | 有大 chunk 非阻断警告 |
| Playwright 默认命令 | 失败；Preview host 不一致，测试开始前超时 | 固定 host 后 9/9 passed |
| `npm audit` | 2 high、0 critical | 更新间接依赖后归零 |
| Docker Compose build | 失败；容器访问 PyPI 报 `SSL: UNEXPECTED_EOF_WHILE_READING` | 未声称通过 |

初次 3 个后端失败分别是：测试误连 PostgreSQL、字符串 UUID 查询错误、报告旧字段 `frozen_segment_count` 未解析。

### 9.2 S2/S6 修复后

| 检查 | 真实结果 |
| --- | --- |
| 后端全量 | 261 passed、2 skipped |
| Ruff | 通过 |
| Mypy | 75 个源文件通过 |
| 前端 Vitest | 30 passed |
| `vue-tsc` | 通过 |
| Vite production build | 通过，仍有大 chunk 警告 |
| `npm audit` | 0 vulnerabilities |
| Playwright | 9/9 passed |
| S2 定向回归 | 21 passed |
| S2 浏览器 | 精确恢复 3/8，页面错误 0，未确认 Apply 无新版本 |
| S5 浏览器 | 完整通过，页面错误 0 |
| S6 浏览器 | 5/5 trials complete，页面错误 0，Dashboard 有行 |
| Docker Compose | 仍因容器网络 TLS EOF 未完成 |

### 9.3 PR #3 UI 与汇总修复

- `npm test -- --run`：32/32 passed。
- `npx vue-tsc --noEmit`：通过。
- `npm run build`：通过。
- Playwright + 本机 Google Chrome：11/11 passed。
- `git diff --check`：通过。

### 9.4 PR #4 小修复

- 前端单元测试：32 passed。
- `vue-tsc`：通过。
- Vite build：通过。
- 浏览器像素测量：顶部图标、菜单图标、侧边栏中心均为 32 px。

### 9.5 PR #5 Agent 运行时配置

- Backend Pytest：273 passed、2 skipped。
- Ruff：通过。
- Mypy：以 Python 3.13 检查 `app`，52 个源文件通过。
- Frontend Vitest：35 passed。
- `vue-tsc --noEmit`：通过。
- Vite production build：通过。
- DeepSeek 真实连接：成功。
- Agent 真实规划：33.52 秒、HTTP 200、12 步、`plan_source=llm`、合规通过。

### 9.6 PR #6 文档合并前最新复测

2026-08-25 在 `d26903f` 功能基线上重新执行：

- `.venv/bin/pytest`：273 passed、2 skipped、1 个 Starlette/httpx 弃用警告，28.53 秒。
- `.venv/bin/ruff check app algorithms tests`：通过。
- `.venv/bin/mypy --python-version 3.13 app`：52 个源文件通过。
- `npm test -- --run`：9 个文件、35 个测试通过，2.95 秒。
- `npx vue-tsc --noEmit`：通过。
- `npm run build`：通过，仍提示若干 chunk 超过 500 kB。
- `git diff --check`：通过。
- 文档敏感信息扫描：未发现 Key 材料。

### 9.7 未执行或未在最新提交后重跑

- PR #5/#6 后没有再次运行 Playwright；最近一次完整浏览器 E2E 是 PR #3 的 11/11。
- PR #5/#6 后没有再次运行 `npm audit`；最近一次记录是修复阶段的 0 vulnerabilities。
- 本文修订没有再次调用真实 LLM。
- 本文修订没有运行 Docker Compose build/up、Alembic migration 或真实 RQ Worker 闭环。
- 最新 Mypy 只检查 `app` 的 52 个文件，并以 Python 3.13 覆盖；不能冒充 Python 3.11 下全仓 75 文件复测。

## 10. S1–S6 测试情况

| 场景 | 用途 | 本轮状态 | 证据与限制 |
| --- | --- | --- | --- |
| S1 | 基础单输入基线 | 历史自动化通过，本轮未做独立人工验收 | 历史无噪测试要求参数误差 <1%、测试 FIT >99.99%；不能当作 2026-08-25 新复测 |
| S2 | 多输入不同滞后 | 通过（分析与安全门） | Dataset/Version 为真实 UUID；精确恢复 3/8；u2 仍不确定，因此按规则没有 Apply、没有新版本 |
| S3 | 长稳态短动态/同构激励 | 历史实验覆盖，本轮未做独立人工验收 | 自评测和敏感性实验已跑；不利结果是 weighted 在单次 S3 略优，IDS 并非永远最优 |
| S4 | 强噪声与异常污染 | 大部分通过，仍有一项未完成 | 正式 V0/V1、Profile、ProcessingRun、DAG 和下载已完成；两个下载 CSV 的最终差异核验仍待人工完成，本轮未重复 Cleaning |
| S5 | 高共线性 | 通过 | Pearson/Spearman/VIF/条件数真实；确认后 V0 4 列 → V1 3 列，均 1200 行，源版本未覆盖 |
| S6 | 异构激励压力 | 修复后通过 | 基线风险高但不再阻断；5/5 trials 完成，最终验证/测试 free-run FIT 90.27%/88.35%，风险 normal |

S2 的“通过”不是指强制走完 Apply，而是指算法结果、证据不确定标记和安全停止均符合要求。S4 不能标成完整通过，直到 V0/V1 下载文件差异最终核验完成。

## 11. 新建 Dataset、Version、Study 与临时数据

### 11.1 S4 正式数据（前一交接阶段保留）

| 实体 | ID/路径 | 状态 |
| --- | --- | --- |
| Dataset `accept_S4_clean` | `f4c27bd2-f27f-40eb-aa61-04988f71f616` | 正式验收数据，禁止误删 |
| V0 | `c13979a1-206e-4a8f-8e37-a22e12f6027d` | 1200×4，原始污染版本 |
| V1 | `caee11ea-9a81-4c85-9d95-4c66b10c3473` | 1200×4，父版本为 V0，Cleaning 派生 |
| V0 文件 | `simulation/f4c27bd2-f27f-40eb-aa61-04988f71f616.csv` | 保留 |
| V1 文件 | `derived/f4c27bd2-f27f-40eb-aa61-04988f71f616/caee11ea-9a81-4c85-9d95-4c66b10c3473.csv` | 保留 |

该历史环境记录：2 个 Version、2 个 Profile、1 个 ProcessingRun、1 条血缘边，Active Version 为 V1。当前 `18010` 临时数据库不包含它们，不能据此推断正式数据已删除。

### 11.2 S2 验收数据

| 实体 | ID/路径 |
| --- | --- |
| Dataset `accept_S2_delay` | `20d9e184-2fe7-48e9-bed0-cede697a2fe2` |
| Root Version | `6a483972-c555-4d85-ab98-580c4119f115` |
| CSV | `simulation/20d9e184-2fe7-48e9-bed0-cede697a2fe2.csv` |
| Ground Truth | `simulation/20d9e184-2fe7-48e9-bed0-cede697a2fe2_ground_truth.json` |
| Manifest | `simulation/20d9e184-2fe7-48e9-bed0-cede697a2fe2.manifest.json` |

Analyze 前后 Version 数均为 1；未确认 Apply 后仍为 1。没有创建 S2 派生版本或半成品。

### 11.3 S5 验收数据

| 实体 | ID/路径 |
| --- | --- |
| Dataset `accept_S5_collinearity` | `d5c86718-63ec-4e18-ad41-6d69ea984c7c` |
| V0 | `26de7451-4cf2-48a4-ae36-890f31493a4e` |
| V1 | `b191a0cd-84e1-404b-b8bc-d242ec1ac371` |
| ProcessingRun | `9c5b4316-85d8-46f0-bfa1-9c775fe02b00` |
| V1 文件 | `derived/d5c86718-63ec-4e18-ad41-6d69ea984c7c/b191a0cd-84e1-404b-b8bc-d242ec1ac371.csv` |

V1 父版本正确指向 V0；V0 下载 1200 行、4 列，V1 下载 1200 行、3 列；Active Version 为 V1。

### 11.4 S6 验收数据

| 实体 | ID/路径 |
| --- | --- |
| Dataset `accept_S6_pipeline` | `d5d107fe-f804-4ce7-812a-eec2764b5385` |
| Root Version | `66cc49de-84cd-47f3-8fd0-4b053a42680f` |
| ARX Model | `417abe11-7d20-45d2-9dda-27c1f24ca2e6` |
| Optuna Study | `889f0231-6cfe-4b1a-8ae1-51174adcbcec` |
| Baseline ProcessingRun | `cd1aa811-e6b7-4629-bbc3-5ec9374f3448` |
| Final Test ProcessingRun | `ad2ccafe-7d86-472e-b877-202b10e9213f` |

S6 没有派生 DatasetVersion；寻优围绕同一 Version 产生模型、Study、Trial 与运行记录。

### 11.5 临时数据与当前临时后端

- 历史 Cleaning API 测试创建过 `contract-cleaning-temp-20260821`；真实 UUID 未记录，旧交接明确标为尚未删除。清理前必须精确确认，不能模糊批量删除。
- 2026-08-22 验收 JSON 与截图位于仓库外：`/Users/shanqicheng/文件/服务外包/acceptance_evidence/`。
- 当前运行后端使用 `/tmp/indusopt-pr-e2e.q5KtH2/e2e.db`：Dataset 0、Version 0、Profile 0、Study 0、Trial 0。
- 当前临时 DB 有 2 条成功的 `agent.copilot` ProcessingRun：
  - `563658bd-c3bc-4c18-93f1-db1480f6499e`
  - `0060822f-24cc-4874-9f49-5a99a61aaf16`
- 没有执行任何清理或删除操作。

## 12. 当前已知问题、失败与未完成功能

1. PR #1、#2 仍为 Open；它们已经被 PR #3 的 `39fa648` 覆盖，应由负责人核对后关闭为 superseded，不应重复合并。
2. Docker Compose 在 2026-08-22 因容器网络 TLS EOF 未构建成功；2026-08-25 Docker daemon 已可访问，但 Compose 栈为空，尚未重新 build/up。
3. 未在可出网环境完成公开工业数据集外部验证；已有结论主要来自仿真和内部验收数据。
4. S4 的 V0/V1 下载文件最终差异核验仍未完成。
5. S1、S3 本轮没有单独的人工浏览器验收；只能引用既有自动化和实验报告。
6. PR #5 后没有重跑完整 Playwright；Agent 设置页和真实模型主要依赖单元测试与人工联调证据。
7. Vite 构建仍提示大 chunk：主包及图表相关 chunk 超过 500 kB，属于性能债务。
8. 最新 Pytest 有 1 个 Starlette/httpx 弃用警告，当前不阻断但未来依赖升级可能需要处理。
9. 运行时 LLM 配置只在进程内存，后端重启会丢失。
10. 系统没有管理员登录、RBAC/SSO 或加密密钥存储，不适合把设置页直接暴露到公网。
11. 当前真实 LLM 依赖外部网络、服务余额、模型名和延迟；失败时能规则回退，但 LLM 文案质量不能保证。
12. 当前产品仍以离散时间 MISO ARX 为主，没有正式 PI/OPC UA 连接、模型注册审批、漂移生命周期或生产级权限体系。
13. 竞赛 PPT 最终视觉复核、演示视频/交互录屏、成员分工与身份字段仍需团队人工完成。

## 13. 当前运行状态

快照时间：2026-08-25 10:36 CST。

| 项目 | 当前状态 |
| --- | --- |
| Git | `docs/lossless-handoff-update`，基于 `origin/feat/versioned-preprocessing-pipeline@2ca32ee` |
| 主后端端口 18000 | 未运行 |
| 临时后端端口 18010 | 运行中，HTTP live 200 |
| 后端命令 | `scripts/serve_e2e.py --port 18010 --state-dir /tmp/indusopt-pr-e2e.q5KtH2` |
| Readiness | `ready / database=connected / queue=connected` |
| 数据库 | E2E SQLite 临时库，不是正式 PostgreSQL |
| Redis | `127.0.0.1:6379` 正在监听 |
| 前端 5173 | 未运行 |
| Docker daemon | 可访问，Server 29.4.0 |
| Docker Compose | `docker compose ps` 无服务，未重新验证 |
| Agent 配置 | `source=runtime`、DeepSeek、`deepseek-v4-flash`、`has_api_key=true`；Key 未回显 |
| 当前 E2E 数据 | 0 Dataset / 0 Version；2 条成功 Agent 运行记录 |

当前后端进程中仍有运行时 Key。完成演示后建议调用“恢复部署配置”或停止该临时后端，使进程内密钥清除；未经授权不要在本文修订过程中主动删除用户配置或停止进程。

## 14. 下一步建议

### P0：负责人接收前

1. 审查本文修订 PR，确认 UUID、测试口径和未完成项表述。
2. 确认 PR base 为 `feat/versioned-preprocessing-pipeline`，不得误选 `main`。
3. 核对 PR #1/#2 已被 `39fa648` 覆盖后关闭，避免重复合并。

### P1：集成与部署

1. 在当前已可用 Docker daemon 上执行 `docker compose build` 和 `docker compose up`。
2. 验证 Alembic 单一 head、PostgreSQL、Redis、RQ worker、health/readiness 和持久卷。
3. 重跑后端全量、Ruff、Python 3.11 Mypy 全范围、前端测试、`npm audit`、Playwright。
4. 用无敏感信息的演示 Key 重测连接、真实 LLM 规划和模型不可用规则回退。

### P2：验收补口

1. 完成 S4 V0/V1 两个下载 CSV 的行列、哈希、缺失、时间戳和污染差异核验。
2. 在公开数据集上补外部验证，明确数据许可、预处理和复现实验协议。
3. 增加 Agent 设置页最新 Playwright 覆盖，包括 404、502、超时、恢复配置和窄屏。

### P3：向 main 与竞赛交付

1. 由负责人整体审查 `feat/versioned-preprocessing-pipeline` 相对 `main` 的差异。
2. 只有整体审查和补测通过后，再创建以 `main` 为 base 的最终 PR。
3. 完成 PPT 视觉复核、演示录屏、成员分工和知识产权待填字段。

## 15. 建议后续使用的技能

- `review`：审查集成分支相对 `main` 的全部差异。
- `gh-fix-ci`：最终 PR 的 GitHub Actions 失败时读取日志并修复。
- `diagnose` 或 `superpowers:systematic-debugging`：处理 Docker、依赖或真实运行问题。
- `webapp-testing`：补 Agent 设置与完整浏览器回归。
- `document-skills:pptx` / `presentations:Presentations`：复核答辩 PPT。
- `document-skills:pdf`：逐页检查最终 PDF 材料。
- `superpowers:verification-before-completion`：在宣布最终项目交付前重新建立证据链。

## 16. 可直接发给负责人的说明

> 本轮以 `e7cc8cd` 为接手基线，完成了 S2/S5/S6 真实验收、两处必要算法策略修复、报告血缘修复、前端 UI 收敛和 Agent 运行时 DeepSeek 接入。功能已通过 PR #3、#4、#5 合并到 `feat/versioned-preprocessing-pipeline`，交接文档通过 PR #6 合并，未操作 main。最新全量复测为后端 273 passed/2 skipped、前端 35 passed，Ruff、Mypy、vue-tsc 和 build 通过；真实 LLM 连接与规划也成功。未完成项包括 Docker Compose 重新实机验证、公开数据集验证、S4 下载文件最终差异核验和竞赛人工材料。PR #1/#2 已被 PR #3 汇总覆盖，建议核对后关闭，不要重复合并。
