---
name: 纯采集驱动改造完成
description: 2026-08-13 新系统移除Excel数据源, 薪资全部由P9采集驱动, 8月数据已导入本地
type: project
---

# 纯采集驱动改造（2026-08-13）

**决策**: 用户明确新系统不再通过上传 Excel 计算薪资，所有薪资数据来自手动采集（P9 采集 API），提交后自动触发计算。不再需要任何 Excel 作为数据源，所有录入进入数据库。

**Why**: 旧系统靠 data/source 目录 Excel 五轨解析驱动计算；新系统改为纯采集模式，数据完全在 DB 中，避免 Excel 格式/解析问题，也支持 Web 端手动录入。

**How to apply**: 涉及"数据来源/加载/重算"的改动时，纯采集模式是唯一路径：`_run_pipeline(month_filter=None)` 从 `collection_submissions` + `attendance_overrides` + `employees` 表重建，不再解析 Excel。

## 已完成的改造

- `_run_pipeline` 纯 DB 模式（去掉 files 参数），main_data 从 `rebuild_main_data_from_collections` + `build_attendance_from_overrides` 构建
- 新增 `load_employees_from_db()`、`build_attendance_from_overrides()`、`_build_db_ab_index()`
- 删除 `scan_source_files`、`/upload-source`、`/download-source`、`_validate_source_file`、`ALLOWED_FILE_TYPES`
- `/reload`、`/set-month`、`/available-months`、`auto_load_source` 改为纯采集模式
- `namematch._AB_INDEX` 从 DB employees 表构建（不再依赖通讯录 Excel）
- data/source 目录已清空（Excel 文件删除，源文件在 `/Users/osong/AI专用分析文件/8月最新原始信息/` 有副本）
- 前端 loadSourceInfo 显示"纯采集模式"，i18n 文案更新

## 8月数据导入（本地）

| 数据 | 数量 | 说明 |
|------|------|------|
| employees | 130 | 新通讯录127人(ID 1-128) + 离职3人(129 EZRA IBRAHIM/130 PAULO LAIZA/131 paulo kisena) |
| overrides | 202 | 薪资配置从服务器迁移（映射新ID） |
| collection_submissions | 40 | 井下11 + 钻工9 + 破碎8 + 出勤12 |
| attendance_overrides | 538 | 8月出勤标记 |
| leave_balances | 108 | 假期余额 |
| leave_requests | 7 | 已通过请假 |

本地验证：gross 20,148,886 TZS；薪资与日明细一致性 0 差异；采集提交自动触发计算（+180,000 立即生效）。

## 修复的 Bug（累计 8 个）

1. `parse_crush_sheet` 选错 sheet（智能表1空壳）→ 优先选 `CRUSH TEAM Production Data`
2. 破碎表头 `How many Bgas -数字` 匹配失败 → 补充匹配 key
3. `load_overrides` 去重：同 effective_from 误删有金额 monthly → 同优先级保留有金额的
4. `calculate_all` 顶层 monthly 满勤与日明细不一致 → 遍历 present_dates 补26天
5. **井下计件人均虚高**（严重）：井下工人被 day_rate/monthly 永久覆盖后从计件分配排除 → 分母错误致人均翻倍（8/3 夜班 8 人只剩 2 人分 229,000 → 人均 114,500）→ 清理历史覆盖残留 + 38 AYUBU default_type 修正为 piece_underground
6. **计薪参数保存无效**：`cfg_ug_mode` 绑定不存在的 `saveUndergroundMode()` + 单价 `||6000` 吞 0 值 → 改绑 `saveConfig()` + 显式保存按钮 + 0 值合法
7. **评分汇总无数据**：`/api/scoring/summary` 读旧表 `scoring_entries`，录入用新表 `scoring_card_entries` → 改为从新表读 + 旧表回退
8. **评分录入范围**：评分 input 加 1-5 clamp（超范围重置）

## 班组与评分（2026-08-13）

- 班组设定：LAMBA LAMBA（班组1）9 人（26/27/33/34/36/38/41/50/52）、SAKA SAKA（班组2）8 人（24/25/42/44/45/47/48/49）
- 评分录入：从 `井下出渣工人评分系统.xlsx` 导入 19 卡 162 行（班组1 9 卡 + 班组2 9 卡 + 管理卡），映射 Excel 短名 → 系统 employee_id
- 评分汇总接口已修复，班组1/2 均能正确返回个人汇总+三闸

## 注意

- ✅ **已部署**（2026-08-14）：服务器运行 main 分支（a4c2189），8月数据已随数据库整体上传（仅本次特殊，日后 git pull 不传库）
- **历史已重写**：全部 113 提交重写移除数据库文件（kilwa.db/wal/shm/b64），git 旧哈希失效（见 project_git_history_rewrite.md）
