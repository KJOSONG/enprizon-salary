---
name: 2026-07-01 会话变更总结(历史存档)
description: 【历史存档】2026-07-01 旧系统(Excel 五轨)时代的变更。纯采集改造后大部分已被取代,仅留作背景参考
type: project
---

> ⚠️ **历史存档(2026-08-15 标注)**:本文件记录 2026-07-01 旧系统时代的变更。自 2026-08-13 纯采集改造起,Excel 上传/`data/source`/`_enrich_crush_with_p_attendance` 链路多已废弃或重构。**当前架构以 AGENTS.md 与项目内 `docs/STATUS.md` 为准**。以下仅留作理解历史决策的背景。

**Why:** 记录关键变更以便未来 AI 实例和开发者快速了解最新状态。

**How to apply:** 涉及当前代码的修改,请勿直接按本文假设现状;先读 AGENTS.md 确认当前实现。

## 变更清单

### 上轮遗留 (本轮未改动)

1. 月薪计算改为 26 天均分 (`core/calculator.py`)
2. `strip_dept` 修复 (`app.py`)
3. 出勤状态字母扩展 R/C
4. 导出报表英文化
5. 新增 Sheet 7 钻工出勤明细
6. 修复 _norm_captain 队长名匹配
7. 补全 all_dates 遗漏 driller 日期
8. 通讯录全员索引

### 9. AGENTS.md 大幅补全
- 修正 calculator.py 描述: 四轨 → 五轨
- 修正净额公式: 加入司机津贴项
- 补充 **16 个遗漏的 API 路由** (logout、离职管理、production、driller-captains 等)
- 修正 3 个路由权限 (/reload、/upload-source 改为 admin，/set-month 改为 editor)
- 补充 backup.sh/restore.sh、无自动化测试说明、i18n 维护方式
- 补充 5 个已知数据边界/特殊情况
- 引用 ARCHITECTURE.md、标注 Gunicorn 日志路径硬编码、破碎计件单价 300TZS 硬编码

### 10. 出勤页面部门筛选 (`app.py` + `templates/index.html`)
- `/attendance` API 响应每行新增 `department` 字段
- 出勤页面筛选区新增 `<select id="attFilterDept">` 部门下拉框
- `renderAttendance()` 首次加载时动态填充部门选项并按部门过滤

### 11. 破碎计件出勤切换完整修复 (`core/calculator.py` + `templates/index.html`)
**核心问题:** 破碎计件员工在空值日期无法手动标记 C 参与计薪，标记后薪资/日工资不变化

**修复链路:**
- 前端 toggleAttDay: 破碎计件员工空值日期循环 `'' → C → A → L → ''`，有自动值的循环 `自动值 → A → L → '' → 恢复自动`
- 后端新增 `_enrich_crush_with_p_attendance()`: 从 attendance_overrides 读取 C/P 标记，注入 crush_data.personnel，返回覆盖列表
- 关键: enrichment 在 `cr_type_excl` 构建**之前**执行，同时将 `per_date_type` 覆盖为 `piece_crush`
- `calculate_all()` 和 `compute_daily_breakdown()` 均已更新
- **不再限制 piece_crush 类型** — 任何员工手动标记 C 都生效

### 12. 预支表更新
- 上传 `预支汇总数据6月.xlsx` (20KB) 到服务器 `data/source/`
- 重启服务 auto_load_source 加载

### 关键架构要点 (记忆强化)
- `per_date_type` 决定逐日单轨归属，`cr_type_excl` 基于此排除非该轨道员工
- `_enrich_crush_with_p_attendance` 必须**先于 `cr_type_excl` 构建**调用，否则手动标记的员工被排除
- 破碎计件单价 PRICE_CRUSH=300 TZS 为硬编码，不可通过 /config API 修改
- 项目无自动化测试，测试依赖 `test-workflow.sh` 数据库替换手工验证
