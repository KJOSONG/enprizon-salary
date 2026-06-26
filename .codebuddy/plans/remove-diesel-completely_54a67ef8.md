---
name: remove-diesel-completely
overview: 彻底移除柴油相关全部功能：前端展示页面、Excel导出、数据解析，涉及 index.html（15处）、app.py（6处）、parser.py（2处）、文档（5处）。
todos:
  - id: remove-diesel-app
    content: 在 app.py 中移除 6 处柴油代码：月份筛选中的 diesel_data、注释、/diesel 路由、Sheet 3 导出、docstring、Sheet 6 导出
    status: completed
  - id: remove-diesel-parser
    content: 在 core/parser.py 中删除 parse_diesel_sheet 函数（L235-274）及其在 parse_all 中的调用（L291-292）
    status: completed
    dependencies:
      - remove-diesel-app
  - id: remove-diesel-html
    content: 在 templates/index.html 中删除 15 处柴油前端代码：导航按钮、快捷卡片、页面 div、STATE 属性、4 处 loadDieselData 调用、loadDieselData 函数、renderDieselCharts 函数、注释
    status: completed
    dependencies:
      - remove-diesel-app
  - id: remove-diesel-docs
    content: 在 DEVELOPMENT_DOC.md 和 overview.md 中删除 5 处柴油文档引用
    status: completed
---

## 用户需求

彻底移除项目中所有柴油（Diesel）相关功能：

1. **取消柴油显示页面**：移除前端 UI 中的导航按钮、快捷卡片、柴油页面 div、图表渲染 JS 函数、数据加载函数及所有调用点
2. **取消 Excel 导出柴油数据**：移除 `POST /export`（Sheet 3 柴油消耗）和 `POST /export/all`（Sheet 6 柴油消耗）两处导出逻辑
3. **取消分析柴油数据**：移除 `parser.py` 中的 `parse_diesel_sheet()` 解析函数及其在 `parse_all()` 中的调用

## 影响范围

- **5 个文件**，约 **28 处**修改
- 不影响产量、薪资、出勤等其他核心功能

## 技术方案

### 修改策略

在各自文件中逐块删除柴油相关代码，按文件维度分批执行：

| 批次 | 文件 | 修改点数 |
| --- | --- | --- |
| 1 | `app.py` | 6 处 |
| 2 | `core/parser.py` | 2 处 |
| 3 | `templates/index.html` | 15 处 |
| 4 | `DEVELOPMENT_DOC.md` + `overview.md` | 5 处 |


### 关键决策

- **完全删除而非注释**：柴油功能已明确不再需要，直接删除代码避免死代码积累
- **parser.py 删除解析函数**：不再解析 Diesel Usage sheet，`main_data` 中将不再有 `diesel_data` 键
- **app.py 月筛选循环移除 `diesel_data`**：因为 parser 不再产生该数据，过滤逻辑也需同步移除
- **前端从 STATE → 数据加载 → 图表渲染 全链路移除**：确保无残留函数调用

### 向后兼容

- 由于是彻底移除功能，无向后兼容需求
- Excel 源文件中仍可包含 Diesel Usage sheet（parser 不会报错，仅跳过）