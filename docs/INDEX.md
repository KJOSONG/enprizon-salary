# INDEX.md — 项目文档地图（新 agent 从这里找一切）

> **阅读顺序**：`AGENTS.md`（架构+纪律，自动加载）→ `docs/STATUS.md`（当前状态）→ 本文件（找细节）。
> 规则：每类信息只有一个权威文件，其他文件只放指针。新增文档时同步登记到本索引。

## 一、状态与进度（最常用）

| 文件 | 回答的问题 | 更新时机 |
|------|-----------|---------|
| `docs/STATUS.md` | 现在 main 是哪个哈希？部署如何？账号？数据状态？挂起什么？ | 每次部署/状态变化 |
| `docs/PROGRESS.md` | 每个批次做了什么、怎么验收、踩了什么坑？ | 每批次完成追加一条 |
| `docs/ROADMAP.md` | 阶段路线图？还有什么没做？已知边界？ | 待办变化时 |

## 二、架构与协作（项目根）

| 文件 | 内容 |
|------|------|
| `AGENTS.md` | 架构速查：数据流水线/五轨计薪/评分三层/出勤状态/计算不变量/命令 |
| `README.md` | 快速上手、部署与命令速查（面向新接手者） |
| `ARCHITECTURE.md` | 设计决策与重构理由（单轨重构 e6b9487、employee_id 迁移、双路径核对）——代码会变、理由不变 |
| `REFACTOR_SPEC.md` | 重构 PRD（需求、验收标准、用户流程），评审后少改 |
| `DEV_WORKFLOW.md` | 工程协作约定（分支模型、提交/推送纪律、部署时机）——工作流唯一权威 |
| `.codebuddy/rules/project-core.md` | 服务器红线/DB 安全/测试产物清理（硬规则） |
| `.codebuddy/rules/code-invariants.md` | 改 app.py/calculator.py/database.py/templates 前必读的计算链不变量 |
| `.codebuddy/rules/team-protocol.md` | 组队并行协议（标准模式专用，PTC 模式禁用） |

## 三、阶段详设（docs/P*.md，按主题分组）

**数据与 API 契约**
- `P0_DATA_MODEL_AND_API.md` — 表结构 + API 契约权威，新表/新接口先查这里

**计薪制度**
- `P25_PIECEWORK_V2_SPEC.md` — 计件 V2 业务权威（凸性加速+月末零和）
- `P25_PIECEWORK_V2_IMPLEMENTATION.md` — V2 工程实现权威
- `P27_MONTH_LOGIC_SPEC.md` / `P27_MONTH_LOGIC_IMPLEMENTATION.md` — 月逻辑
- `P28_LEAVE_RULES_SPEC.md` — 请假规则

**评分与数据台**
- `P15_SCORING_BONUS_ALIGNMENT.md` — 评分三层对齐手册
- `P15_DASHBOARD_REFACTOR.md` / `P15_IMPLEMENTATION_DESIGN.md` — 数据台重构
- `P31_DASHBOARD_TEAM_SPEC.md` / `P31_DASHBOARD_TEAM_PREVIEW.html` — 班组预览

**OA 与权限**
- `P12_OA_PROFILE_COLLECTION_REFINEMENT.md` / `P13_OA_NOTIFY_QA_REFINEMENT.md` / `P14_USER_FEEDBACK_2026_08_13.md` — v5~v7 反馈迭代详设
- `P18_PERMISSION_REFACTOR.md` / `P18B_PERMISSION_UI_REFACTOR.md` / `P18C_PERMISSION_UI_V2.md` / `P18_PERMISSION_QA.md` — 权限重构各阶段
- `P29_PERMISSION_V2_SPEC.md` — 权限 V2.1（已部署，需求冻结，接手必读）

**移动端**
- `P16_MOBILE_DESIGN_ALIGNED.md` / `P16_MOBILE_FRONTEND_SPEC.md` / `P16_MOBILE_QA_REPORT.md`

**组织**
- `ORG_RESTRUCTURE_2026_PLAN.md` — 2026 部门重整方案（已实施，见 PROGRESS 2026-10-25）

## 四、批次实施档案（.codebuddy/specs/）

组队任务的方案/审查/QA 原件，索引：`.codebuddy/specs/INDEX.md`。
涵盖 P38~P54、perf 1-3、oa-ux、oa-salary-change、audit-fixes-202611 等 14 个任务。

## 五、记忆体系（CodeBuddy 跨会话）

**项目内（进 git，任何 agent 可读）**
- `docs/archive/memory/` — 历史交付记忆归档 **18 篇**（P4-P23、OA 重设计、纯采集、git 重写等），逐篇索引见其 `README.md`，需要细节时按 PROGRESS.md 指针查阅

**项目外（`~/.codebuddy/projects/Users-osong-AI专用分析文件-enprizon-salary/memory/`，自动加载索引 MEMORY.md）**
- 纪律类：`feedback_workflow.md`（本地→批准→推送→部署）、`feedback_coding_three_rules.md`（clamp/哨兵/落库形态）、`feedback_ui_no_prefill.md`（弹窗不预填）、`feedback_ui_permission_control.md`、`feedback_test_artifacts.md`、`feedback_memory_classification.md`、`feedback_task_tracking.md`
- 计算权威：`salary_calc_logic.md`（**改计算代码前必读**）、`scoring_model_ref.md`
- 事故档案：`project_oom_incident_20260904.md`、`project_mobile_white_screen_20260904.md`、`project_shell_deadlock_rootcause.md`
- 基础设施：`cloud_server.md`、`backup_spec.md`、`keju_local_credentials.md`、`server_superadmin_credentials.md`、`project_kilwa_secret_key.md`、`project_nssf_enrollment_model.md`
- 模式与团队：`project_ptc_mode_rules.md`（开工先判 PTC/标准模式）、`project_team_config.md`
- 指针文件：`project_current_state.md` → STATUS.md；`phase_tracker.md` → PROGRESS.md/ROADMAP.md

## 六、测试与脚本

- `tests/` — pytest 单测（改计算链后跑全量）
- `scripts/` — 数据修复/迁移脚本（norm_event_dept_names.py、migrate_ml_supervisors.py、verify_salary_identity.py 等）
- `test-workflow.sh` — 手工测试数据库隔离（start/swap/restore/clean）
- `backup.sh` / `restore.sh` — 服务器每日备份与恢复
- `cleanup-test-artifacts.sh` — 测试产物 TTL 清理（任务完成即清是硬规则）
