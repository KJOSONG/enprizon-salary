---
name: P22-FIX 日工资明细缺失
description: 2026-08-16 日工资明细只105人;calc_day_salary以override_type优先判定日薪;UG部门day_rate员工36/52计入;LINDI PROJECT实际月薪
type: project
---

# P22-FIX: 日工资明细缺失 UG 部门 day_rate 员工（2026-08-16 已部署 main=904246e）

**Why**: 用户发现服务器日工资明细网格只有 105/106 人显示，询问原因。排查发现核心 bug + 一个关键认知校正。

**How to apply**: 修改日薪判定逻辑时必须「override_type 优先」——不要只信 `default_type`。

## 根因

`core/calculator.py` 两处判定日薪的逻辑只认 `overrides` 表里的 day_rate 覆盖记录，不认员工自身 `default_type='day_rate'`：
1. `calc_day_salary()` 的来源2 `is_overridden_day_rate`（日工资明细数据源）
2. `compute_daily_breakdown()` 的 `_has_dr_ov`

**后果**：UG 部门 day_rate 员工（36 FRANCIS、52 YUSUPH，均无 override）通过井下出渣采集提交 D/N 出勤 → 薪资总表（`calculate_all` 用 `present_dates`）正确计日薪 220,000，但日工资明细完全缺失 → 网格只有 105 人。

## 修复

两处判定改为 `_eff = override_type or default_type; if _eff == 'day_rate': return True`，并移除原「永久 day_rate 覆盖直接返回 True」分支（永久覆盖已由 override_type 体现）。验证：日明细 105→107，36/52 逐日 20,000×11 天=220,000，与薪资总表一致；双路径差额 -34（既有舍入）。

## 关键认知校正（勿再犯）

**ENPRIZON LINDI PROJECT 部门 8 人（id=1-7,80）实际都是月薪**：
- `employees.default_type` 全部是 `day_rate`（误导！）
- 但 `overrides` 表有**永久 monthly 覆盖**（id=1~5 纯 monthly 60万/150万/86.5万/100万/100万/120万；id=6 有临时 day_rate 区间 + monthly 120万；id=7/80 有永久 day_rate + monthly 100万/70万）
- 运行时 `override_type='monthly'` → 薪资总表 gross=月薪全额，日明细 26 天

**教训**：判断员工薪资类型永远要看运行时 `override_type`（`_run_pipeline` 从 overrides 推导），不能只看 `default_type` 列。修复时若只看 default_type 会把 id=7/80 误判为日薪。

## 验证方式（可复用）

生产库一致性导出（`sqlite3.backup`）→ scp 到本地 `/tmp/kk_prod_data/kilwa.db` → `_run_pipeline(month_filter='2026-08')` + `compute_daily_breakdown` → 对比 `salary_result` 与 `dw` 逐人逐日。生产库拉到本地是用户授权的（2026-08-16），测试完清理。
