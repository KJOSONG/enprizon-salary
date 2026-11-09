---
name: P15 评分奖金计算对齐
description: 2026-08-13 井下评分奖金三层模型对齐手册实施，已提交 8619c08
type: project
---

# P15 井下评分奖金计算对齐（2026-08-13）

## 决策

以《生产团队绩效考核体系管理手册.docx》为权威需求，修复评分奖金链路 4 处偏差 + 落地产量层公式 + 客观层实际出渣自动汇总 + 前端展示。commit `8619c08`。

## 三层模型数值化

**① 产量层（奖金池生成）**：
```
总池 = max((当月 NICKEL(H) 车次 − 600), 0) × 20,000
半池 = 总池 × 50%
```
- 仅 NICKEL(H) 参与；NICKEL(L)/MAWE 不计；<600 车次无池
- 数据源：井下采集 `collection_submissions` payload 的 `day.nh + night.nh`

**② 客观层（发放比例）**：
```
S = R1 × 70% + R2 × 30%
R1 = 实际出渣量 ÷ 计划出渣量（不封顶）
R2 = 有效作业时间 ÷ 在井总时长（上限100）
月度 S = 全月当日 S 均值
```
- 计划=0 时 R1 不参与，当日 S = R2 × 30%
- 实际出渣量 = 当日井下总产量（nh+nl+mw 车次）自动汇总；计划出渣量手工录入
- 发放比例五档：≥90→100%, 80-89→95%, 70-79→90%, 60-69→80%, <60→70%

**③ 主观层（个人份额）**：
- 单班实际池 = 半池 × 发放比例
- 个人奖金 = 班实际池 × (个人系数 ÷ Σ本班系数)
- 系数：≥85→1.2, 70-84→1.0, 60-69→0.8, <60→0.5

## Why

旧评分奖金计算与手册有 4 处偏差（半池硬编码、发放比例档位不齐、R1 数据源不对、汇总与奖金系数不共享）。

## How to apply

- `_get_scoring_bonus(data_folder, employee_id, month_prefix, pool_info, team_id)` 是唯一奖金来源（R4 重构）
- 半池禁止硬编码（50%）
- 发放比例统一在 `get_monthly_objective`（90/80/70/60 五档）
- summary 与奖金计算共用同一套系数函数，避免双源偏差

## 参考文档

- 权威需求: `/Users/osong/WorkBuddy/坦桑法规/output/矿区管理/中文文档/生产团队绩效考核体系管理手册.docx`
- 仓库: `docs/P15_SCORING_BONUS_ALIGNMENT.md` + `docs/P15_IMPLEMENTATION_DESIGN.md`

## 当前状态

- ✅ 已合并 main 并部署(2026-08-14,历史重写后 a4c2189;旧哈希 8619c08 已失效)
- 三层模型实现细节在 `_get_scoring_bonus` + `get_monthly_objective`(core/database.py),见 AGENTS.md「评分奖金三层模型」
