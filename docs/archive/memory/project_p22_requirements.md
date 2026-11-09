---
name: P22 一批需求
description: 2026-08-16 自助改密/OA历史类型筛选/档案姓名上移/D-N高对比色/移动端档案薪资显示规则;已部署 main=b33e4e0
type: project
---

# P22 一批需求（2026-08-16 已部署）

**Why**: 用户一次性提出 6+2 项改进：自助改密、审批历史筛选、档案页姓名位置、出勤网格 D/N 看不清、UG 部门日薪/月薪员工计薪注意事项、移动端档案薪资显示规则（ENPRIZON LINDI PROJECT 部门 + 其他部门）。

**How to apply**: 已全部落地（main=b33e4e0，5 commit 合并 feature/p22）。改相关代码时注意以下已确认的语义：

## 各需求落地要点

1. **R1 自助改密**：后端 `/api/admin/change-password` 仅 `@login_required` + 旧密码验证，无角色限制；桌面 ☰ 菜单"改密"、移动端下拉"改密"对所有登录用户可见。纯验证，无代码改动。
2. **R2 审批历史类型筛选**：`core/database.py get_processed_events(data_folder, event_type=None)`；`/api/oa/history?type=`；前端 `oaHistoryTypeFilter` 下拉（选项由 `EVENT_LABELS_MAP` 动态创建）。**踩坑**：动态创建带 `data-i18n` 属性的 option 才会随语言切换重译（applyI18n 的 querySelectorAll 覆盖 textContent），首次 t() 填充 + 后续切换都正确。
3. **R3 档案页姓名在别名上方**：展示页姓名 h2 在上、别名 muted 在下；编辑表单姓名输入框在上、别名在下。
4. **R4 D/N 高对比色**：`style.css` 新增 `--st-d`/`--st-n`（亮色 hsl(200 60% 45%)/hsl(180 50% 40%)，暗色更亮变体），替换原近白的 `--accent`/`--cyan`。应用到 statusStyle、筛选弹窗、日工资表 D/N 表头按钮。
5. **R5 UG 部门日薪/月薪员工**：Production TEAM （underground）部门但 day_rate/monthly 员工，即使出现在井下采集 D/N 名单，也不参与井下计件（P21 M6 `ug_type_excl` 双条件），按自身类型计薪，D/N 天计入出勤（`calculator.py:927-930`），井下总额守恒。QA 内存构造验证通过，无 bug。
6. **R6/R7 移动端档案薪资显示**：`mobile.html renderEmpProfile` 删 7 人硬编码名单 `SALARY_HIDDEN_NAMES`，改 `isUgDept` 部门判断（trim === 'ENPRIZON LINDI PROJECT'）。UG 部门隐藏薪资类别行 + 薪资概览；其他部门显示薪资类别**只含类型名不含金额**，薪资概览（gross/net）保留。

## 验证报告

- `_work/P22_QA_VERIFY_REPORT.md`（R1/R5）
- `_work/P22_QA_REGRESSION_REPORT.md`（R2/R3/R4/R6/R7 + 回归）

## 部署

- 合并 commit `b33e4e0`（--no-ff，5 commit：4 需求 + 4116574 翻译修复）
- 服务器备份：`data/backups/kilwa_before_p22_20260816_045954.db`
- 部署后验证：HTTP 200 / 特征 grep 全在 / 0 日志错误
