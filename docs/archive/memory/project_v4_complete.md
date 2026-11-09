---
name: v4/v5 完成 + v6 需求对齐
description: 2026-08-12 P0-P12 完成+v5 验收通过，v6 PRD 已对齐(P13 待实施)，服务器未部署
type: project
---

# v4/v5 完成 + v6 需求对齐（2026-08-12）

> **2026-08-13 更新**: 新增**纯采集驱动改造**（移除 Excel 数据源），8月数据已导入本地。详见 [project_pure_collection.md](project_pure_collection.md) 与 AGENTS.md「重构状态」。"重构状态"现为 P0-P13(纯采集) 本地验证通过。

## 状态（2026-08-15 更新）
- **P0-P19 全部完成并部署**（main=491ba33）；refactor 分支已并入 main 作废
- **纯采集改造**（2026-08-13）：移除 Excel 数据源，`_run_pipeline` 纯 DB 模式；8月数据已导入本地（employees 130 / overrides 202 / collection_submissions 40 / attendance_overrides 538 / leave_balances 108 / leave_requests 7）
- 历史已重写（旧哈希如 2b48bd0 已失效）；部署链与当前状态见项目内 `docs/PROGRESS.md` 与 `docs/STATUS.md`
- 本地 KEJU 密码 = `0000`（2026-08-12 用户要求）

## v5 有效反馈（10 条，1 条笔误剔除）
- #1 OA 三申请（入职/调岗/离职）升格为员工管理**侧栏平级子页**，入职申请=完整档案表单，审批后自动入列表
- #2 员工档案从弹窗改**独立完整页面**（`#employees/profile?id=`），头像**简历照尺寸**（96×120px，3:4）
- #3 档案页**年假/调休/病假三类余额均显示且可修改**（写审计）
- #5a 姓名**可选中复制**（不跳转），点击才跳档案页
- #4 井下出渣采集**三列带标签**（NICKEL(H)/(L)/MAWE）+ **Day/Night 各自独立 Remark**
- #5b 钻工**队长名单化**（新表 `driller_captains`，当前 3 人）+ 按钮改"**添加队伍**"（先选队长再生成槽位）
- #6 评分模块改名"**评分系统**"，补 nav_scoring i18n（当前缺键直接显示原始 key）
- #7 "驾驶"勾选从出勤收集**移到井下出渣采集**选人弹层（仅司机名单内）；出勤收集改**按部门**提交
- #8 选人弹层/选中框**统一样式**对齐（`emp-chips` 类）
- #9 计薪参数页**删除旧"司机津贴"卡片** + saveConfig/resetConfig 移除 driver_allowance 字段；**新增钻工队长名单维护**
- #10（原"计薪参数页面加入…"）**用户确认为笔误**，忽略，不新增任何参数项

## v6 有效反馈（10 条，2026-08-12 v5 验收后）
- #1 员工列表**部门筛选不生效**（根因：`renderEmployeeTable` 每次重建下拉重置选中值）
- #2 员工档案子页**移出侧栏**（保留 `#employees/profile?id=` 直达）
- #3 OA **自审规则分角色**：super_admin 可自批；其他角色自提交仅可驳；审批卡片**可展开看 payload 详情**
- #4 请假申请**升格侧栏子页**，移出待审批页
- #5 侧栏折叠后**底部区样式优化**（中英/登录/改密/退出）
- #6 入职表单**加头像上传**（≤2MB PNG/JPG）
- #7 入职提交后**自动进待审批页**
- #8 顶部**通知铃铛/红点**（列"待你审批"可跳转）
- #9 **super_admin 后台指定审批人**（非提交人操作；未指定走默认流）
- #10 全页面字段**中英双语审查**（硬编码中文 113 处清零）

## 关键交付（P6-P11，对应 17 点用户反馈）
- P6 顶部交互：删登录月份选择器/搜索 scope、员工档案页合并抽屉、修复 /employees 500
- P7 员工字段：gender/date_of_birth/avatar_path 列 + 头像上传/删除 API + 字段类型校验 + 薪资类别可改
- P8 OA 合并 + 病假：OA 3 表单嵌入员工页、**审批落库闭环**（apply_approved_event）、病假免审 14 天落 P、姓名索引 typeahead
- P9 数据采集：4 表单（井下 D+N 双段/钻工 N 槽位/破碎/出勤收集）+ 历史再编辑 + **reload 持久化**（rebuild_main_data_from_collections）
- P10 评分：employee_groups 班组表（LAMBA/SAKA）+ custom_number/team_id + 一张张卡翻卡 + month 维度 + 覆盖更新
- P11 系统清理：删源文件管理 UI（API 保留）、司机津贴 is_driver 按天机制、driver_allowance 列、井下计件→生产薪资

## 验收中发现并修复的重要 bug（教训，非显而易见）
- `/employees` 500：重复 def 嵌套（装饰器注册空壳函数）
- `database.py leave_count` execute 缺参数元组 → `/api/employees/{id}` 500
- `scoring_card_batch` 无 try/finally → IntegrityError 连接泄漏 → **全库写锁死**（所有写请求 locked 直到重启）
- `scoring_cards` UNIQUE 不含 month → 跨月评分 500（重建表迁移）
- `compute_daily_breakdown` 引用未定义 `scoring_employees` → 日工资页 + /export/all 500
- `/salary` result 缺 month 字段 → 登录后 period-bar/评分页月份为空
- 旧 `_apply_driver_allowance`（按部门名/岗位匹配）是假机制，v3 手动产量（shift_additions）也从不参与计薪——均已根治

## 部署注意（Why: 服务器首次启动会自动迁移）
1. **先备份**：服务器 `bash backup.sh` 或一致性备份
2. 服务器 `git pull && systemctl restart enprizon-salary`（main 分支,不再 checkout refactor）
3. 首次启动 init_db 自动 ALTER：employees 新列（gender/dob/avatar/custom_number/team_id）、leave_balances 病假列、attendance_overrides is_driver、scoring_cards month UNIQUE 重建、新表（collection_submissions/collection_history/employee_groups）
4. **KILWA_SECRET_KEY 需设置**（部署前确认 systemd 环境变量，否则重启会话失效）
5. 服务器 Nginx 子路径 KILWA_SCRIPT_NAME=/salary 不受影响

## How to apply
- 新会话若处理本仓库，先读 REFACTOR_SPEC.md v6（权威 PRD，注意 §0.2 v6 增量）+ AGENTS.md（架构）+ docs/P12 与 docs/P13 详设 + 本记忆
- P12 代码已改未提交；P13 是文档定稿、代码未动阶段；实施前逐条对照 P13 详设的"现状代码→v6 目标→改动点"
- 本地 KEJU 密码 `0000`（2026-08-12 重置）；`user/qweasd` viewer
- 若涉及部署/推送，先确认用户意图再动（工作流：本地→推送→服务器，需明确批准）
