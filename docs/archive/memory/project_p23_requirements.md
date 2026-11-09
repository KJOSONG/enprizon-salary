---
name: P23 四项需求
description: 2026-08-16 照片放大压缩/加班申请计费/审计日志移权限页/缓存同步bug修复;已部署 main=985411c
type: project
---

# P23 四项需求（2026-08-16 已部署）

**Why**: 用户 4 项需求：①头像点击放大预览+上传压缩 ②审批加加班申请(时间区间自动算小时,审批后按公式计加班费) ③审计日志移入用户权限页 ④质疑"重新计算/重新加载"意义——结果挖出真实缓存同步 bug。

**How to apply**: 已全部落地（main=985411c，feature/p23 4 commit）。改相关代码注意：

## 各需求落地要点

1. **R1 照片**：头像点击弹大图预览（桌面 modal `avatarPreviewModal` / 移动 sheet）；上传走 `compressImage()`（降采样 1024px + canvas.toBlob JPEG 迭代降质至 ≤2MB），接入上传 `uploadEmployeeAvatar` 和入职 `handleHireAvatar`。后端 2MB 校验保留兜底。
2. **R2 加班**：
   - 新表 `overtime_records`（event_id 外键/employee_id/date/start_time/end_time/hours/amount/note），`init_db` 自动建。
   - `employee_events` 支持 `event_type='overtime'`，payload 存 date/start_time/end_time/hours/note；`ALLOWED_APPROVAL_EVENT_TYPES` 加 'overtime'。
   - 时长计算 `_calc_overtime_hours`（core/database.py）：0.5h 一档向下取整、end<start 跨天、>12h 拒绝；前端实时算 + 后端审批重算覆盖防伪造。
   - 审批通过 `apply_approved_event` overtime 分支落 overtime_records；撤销 `revoke_event` 删除回滚。
   - **公式**：`hours × overtime_base / overtime_work_days / overtime_hours_per_day × overtime_rate`，默认 400000/26/8/1.5。参数在 settings config 四个键，计薪参数页可改（`/config` API）。
   - **计算**：加班费并入 gross（`calculate_all` 加 `ot` 层，独立 `overtime` 展示字段 + `total_overtime`），日明细 `compute_daily_breakdown` 逐日叠加——保证日明细=薪资页。NSSF 默认计入（gross 一部分）。
3. **R3 审计日志**：`templates/index.html` 审计 card 从系统配置页移到用户权限页（双 Tab 页底部），原入口移除。**踩坑**：移动时注意 `page-settings` 闭合 `</div>` 不能丢，否则 DOM 嵌套错乱（dev 已修复）。
4. **R4 缓存同步 bug（用户实测 2100万→2400万根因）**：
   - 根因：`_recalc_internal`（重新计算按钮）用缓存 `APP_STATE['employees']`；`/reload` 走 `_run_pipeline` 从 DB 重新加载+重新推导 override_type。而 `api_employee_update`/`api_employee_salary_type`/`remove_override*` 只写 DB 不刷缓存 → 改薪资后金额陈旧。
   - 修复：封装 `_refresh_employees_cache()`（内部调 `_run_pipeline` 全量重建，override_type 推导/清零逻辑集中）+ `_sync_employee_cache()`（轻量单字段同步，用于 avatar/annual_leave_override 纯展示字段）。9 处端点接入：save_override/remove_override/remove_temp_override/remove_override_by_id/restore_employee/api_employee_update/api_employee_salary_type/api_employee_avatar_upload/delete。`save_bonus_penalty` 不需要（bonus 每次从 DB 读）。
   - `/reload` 保留为兜底；`/recalculate` 保留（采集提交依赖 `_recalc_internal`）。

## 验证报告
- `_work/P23_QA_REPORT.md`（QA 19/19 PASS + 截图 r1_avatar_preview_modal.png / r1_mobile_avatar_sheet.png）
- 线上验证：total_gross=24,704,278、overtime_records 表已建、加班参数默认值正确、0 日志错误

## 部署
- 合并 commit `985411c`（--no-ff，4 commit）
- 服务器备份：`data/backups/kilwa_before_p23_20260816_075750.db`
- 部署后 `overtime_records` 由 init_db 自动创建（已验证列结构完整）
