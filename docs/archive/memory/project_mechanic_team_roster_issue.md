---
name: 部门重整花名册错位(Mechanic Team 两人)
description: 2026-10-27 排查 Halid(60)/JEREMIAH(170) 出勤提交找不到——调岗事件链 new_department="Mechanic Team" 与重整后部门树脱节;全库审计结论与待批修复方案
type: project
---

# 部门重整 × 调岗事件链错位（2026-10-27 排查）

**现象**：Halid hasan(60) 与 JEREMIAH COSMAS PHILIPO(170) 在出勤提交时于 Engineering & Maintenance Department 下找不到（部门重整后）。

**根因**：两人各有已批准 OA 调岗事件（#291 eff 2026-09-12 / #399 eff 2026-10-02）指向旧部门 **"Mechanic Team"**；重整把该部门并入 E&M 时只改了 `employees.department`，**未迁移事件 payload**。P40-d `_apply_transfer_day_view`（app.py:4137）对生效日之后的按日归属以事件链 `new_department` 为权威 → 两人采集花名册始终归 "Mechanic Team"，而该名不在 DEPT_TREE（index.html:4019），只能从"其他部门"组摸到。`_roster_stale_error`（app.py:4649）还会拦截部门不符的提交。

**实际影响**：60/170 的出勤标记 10-01~10-22 连续完整（QIFEI 10-20~22 经"其他部门→Mechanic Team"提交成功，955/956/957）；**10-23 起无提交**，缺 10-23~10-26 共 4 天（10-27 当天待提）。注意：查询 attendance_overrides 时 LIMIT 会截断造成"断档"假象，须 GROUP BY MAX(date) 核实。

**全库同类审计结论（生产库，2026-10-27）**：
- 最新已批调岗目标 ≠ 当前部门的在职员工：仅此 2 人
- 在职员工部门全在两级树内；UG 班组 team_id 全有效；driller_captains 4 条引用完整；overrides.team_id 无脏值；无未来 hire_date；status 仅 active/dismissed；pending transfer 仅 #548（员工25→UG班组4，10-27 生效，树内）
- Minor：177 MATIAS（Sorting Team）残留 team_id=3（旧 UG 班组），无功能影响
- 事件链存留树外历史部门名（Sort Crush/Logistics/分拣破碎[EN:Sort Crush]/Sort Crush/Crush Piece Rate/Production TEAM （underground））——目前无人在最新调岗目标上踩中，但将来再调岗/重整会复现同类错位（潜在雷）
- 旧部门名提交兼容正常：Logistics/Sort Crush 等每日提交的标记抽样全部落库，无静默丢失

**✅ 已修复并部署（2026-10-27，用户批准+授权直接部署）**：`scripts/norm_event_dept_names.py`（commit 5f424c4）对全部 approved transfer 事件做遗留部门名归一：'Mechanic Team'→'Engineering & Maintenance Department'、'Production TEAM （underground）'→'Production TEAM'（无条件结构性改名）；Sort Crush 家族→员工现部门∈{Sorting,Crushing}否则默认 'Sorting Team'；Logistics 家族→现部门∈树内非UG否则 'Materials & Logistics Department'（守卫：绝不把非UG旧名映射进UG）。生产 31 条事件归一（含 #291/#399），audit_log event_dept_norm×31，遗留名清零。**验证**：生产副本沙盒 8/9/10 月薪资逐分 0 差异（before/after JSON diff identical）+16 项花名册断言全 PASS+pytest 49/49+幂等复跑 0 变更；生产 dry-run 与本地逐条一致。备份 data/backups/kilwa_before_deptnorm_20261027_2140.db（只留此 1 个，旧 mlsup 备份已按规则清除）。纯数据变更未重启。**遗留**：60/170 的 10-23~10-26 出勤标记缺口（用户明令不用 AI 补录，由业务侧自行处理）；170 生效日(10-02)前按日归属显示 'Sorting Team'（'Sort Crush' 默认后继，树内、薪资无影响）。测试产物 _work/dept-norm、/tmp 脚本与副本均已清理，git 干净。

**教训**：组织重整只改 employees 表不改历史事件 payload，而采集花名册按事件链归边——这是同族问题第三次（MICHAEL PETRO、LARI、本次）。今后重整/调岗数据操作必须同步迁移事件 payload（此脚本可复用/扩展）。

**教训**：组织重整只改 employees 表不改历史事件 payload，而采集花名册按事件链归边——这是同族问题第三次（MICHAEL PETRO、LARI、本次）。
