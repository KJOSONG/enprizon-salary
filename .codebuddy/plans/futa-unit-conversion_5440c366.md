---
name: futa-unit-conversion
overview: 在"耗材统计"柱状图的 FUTA 数据集渲染时，将原始值除以 164 后再显示，底层数据保持不变。只需修改 templates/index.html 第 1580 行的一处 JS 代码。
todos:
  - id: futa-conversion
    content: 在 templates/index.html 第1580行，将 FUTA 数据映射 `d.futa||0` 改为 `(d.futa||0)/164`，实现前端展示层的单位换算
    status: completed
---

## 用户需求

修改钻工FUTA（Consumables）数据的单位转换逻辑。原数据中该物料的单位为"支"，现需在系统UI界面展示时，将原数据值除以164，在UI层显示计算后的结果（原值/164），同时保持底层数据的原始单位"支"不变。

## 核心功能

- 前端Chart.js"耗材统计"柱状图中FUTA的数值展示 = 原始值 / 164
- 后端parser/calculator/API不做任何修改，底层数据保持原始单位"支"
- WAYA和KIBIRITI两个耗材数据不受影响，保持原样

## 技术方案

### 实现策略

**仅修改前端JavaScript渲染层**，在 `templates/index.html` 第1580行将 FUTA 数据映射从 `d.futa||0` 改为 `(d.futa||0)/164`。

### 关键决策

- **为什么只改前端**：用户明确要求"UI界面展示时"转换，底层数据不变。前端换算是最小影响范围的方案。
- **为什么不改后端**：改后端API会污染数据源，且会影响潜在的API调用者（如果有的话）。保持后端数据纯净，前端负责展示逻辑是最佳实践。
- **为什么要除以164**：用户指定的换算比例。

### 影响分析

- **修改文件**：仅 `templates/index.html` 1个文件，1行代码
- **不受影响**：parser.py、calculator.py、app.py 及其他所有后端代码
- **不受影响**：SQLite数据库、Excel源文件中的原始数据
- **向后兼容**：前端只改变Chart.js的数据点，不影响其他功能