# IndusOpt 工模智优

面向流程工业建模工程师的**工业数据优选、系统辨识与 Agent 工作流平台**。赛题为 2026“数字马力杯”第十三届浙江省大学生服务外包创新应用大赛 A14（和利时）。

工程师上传多变量工业 CSV 并描述任务，平台完成画像、清洗、动态片段优选、时滞补偿、共线性处理、建模评价和反馈寻优，最终交付优选数据、模型关联清单与可追溯图文报告。

**给 AI：先读 [AI_CONTEXT.md](AI_CONTEXT.md)。** 这里说明阅读顺序、源码入口、最新进展、证据口径和后续工作。

## 这份仓库包含什么

这是 2026-10-30 从本地项目整理的精简快照：保留当前前后端源码、算法、测试、数据库迁移、启动配置、核心设计、实验摘要，以及当天的 17 页答辩策划。原项目的 Git 历史、工业 CSV、数据库、凭据、依赖、PPT/视频和大型中间结果未上传。详细范围与 SHA-256 清单见 [上传说明](docs/UPLOAD_SCOPE.md) 和 [文件清单](docs/UPLOAD_MANIFEST.json)。

| 关注内容 | 入口 |
|---|---|
| 项目做什么、有什么价值 | [项目完整介绍](docs/project/项目完整介绍.md) |
| 最新软件整合与实际验收 | [2026-10-07 整合记录](docs/integration-20261007.md) |
| 赛题要求与完成情况 | [需求核查](docs/requirements/implementation-audit-20261004.md) |
| 算法设计与评价口径 | [算法规范](docs/algorithms/algorithm-specification-v2.md) |
| 架构、数据流、版本血缘 | [架构文档](docs/architecture/) |
| 实验结果及失败边界 | [实验报告](docs/experiments/) |
| 当前答辩方向 | [17 页策划](docs/presentation/20261030/17页叙事与内容策划.md)、[评审依据与调整建议](docs/presentation/20261030/官方评审依据与PPT调整建议.md) |
| 具体操作 | [用户手册](docs/manual/用户手册.md) |

## 核心实现

- **质量约束 D-最优优选**：先通过质量门控，再选择补充信息的动态窗口，减少重复信息。
- **真实建模与反馈**：ARX/FIR、自由仿真评价、Optuna 参数搜索；多步 OE 为实验选项。
- **受约束 Agent**：大模型生成结构化计划，白名单校验、关键操作确认，Python 工具执行计算；无模型配置时使用确定性流程。
- **可追溯交付**：保留数据版本和模型来源，报告数值绑定实际证据，最终导出 CSV 与 Manifest。

前端为 Vue 3 / TypeScript / Element Plus / ECharts，后端为 FastAPI / Pydantic / SQLAlchemy，算法使用 NumPy / SciPy / Optuna，部署使用 PostgreSQL、Redis / RQ。

## 当前验证范围

2026-10-07 的真实锅炉流程记录：13 步成功，DeepSeek 规划与报告无回退，6 幅图、54 个绑定数值，导出 3172 行；冻结模型 Test 自由仿真 RMSE 1.8870、FIT 49.55%，存在输入范围外推。4 次 Trial 用于贯通演示，最佳为 Trial 0，尚不能证明收敛或反馈增益。

双水箱有独立记录的模型部分对照，卷绕有同运行时间留出验证；蒸馏跨运行迁移仍失败。不同协议的数字不能混用，详见[事实核对](docs/project/事实核对与旧稿勘误.md)。既有测试结果属于原项目历史记录，本次上传未重跑全量业务测试。

本地 PostgreSQL / Redis / 前后端已运行并验收；Docker Compose 配置检查通过，镜像构建与容器启动仍待实机验收。当前无完整登录和权限系统，适用于受信任本地/内网环境。

## 安装与运行

准备 Python 3.11+、Node.js/npm、PostgreSQL 16 与 Redis。首次安装：

```bash
cd backend
python3.11 -m venv .venv
.venv/bin/pip install -e '.[dev]'
cp .env.example .env
cd ../frontend
npm ci
cd ..
python3 scripts/run_platform.py
```

启动器查找本机 PostgreSQL/Redis 可执行文件，创建独立本地服务、执行 Alembic、构建前端并启动 API；端口参数见 `python3 scripts/run_platform.py --help`。浏览器默认入口 <http://127.0.0.1:5173>，持久化内容保存在忽略目录 `.runtime/platform`。

可选容器入口（仍待实机验收）：

```bash
docker compose --env-file backend/.env up --build -d
```

容器浏览器入口为 <http://localhost:8080>。LLM 参数只写入本地 `backend/.env`；默认 `INDUSOPT_LLM_PROVIDER=none` 可离线运行。

## 开发检查

```bash
cd backend
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check app algorithms tests scripts
cd ../frontend
npx vue-tsc --noEmit
npm run build
npm test
```

真实工业数据实验需另外准备原始公开数据，并修改脚本使用的数据路径；精简仓库未包含原电脑的数据和完整实验封存包。固定种子的仿真与算法测试代码已保留。
