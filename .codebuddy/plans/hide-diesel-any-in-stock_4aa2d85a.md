---
name: hide-diesel-any-in-stock
overview: 从柴油报表 `/diesel` API 响应中移除 `any_in_stock` 字段，确保前端完全不接收、不展示"Any in Stock?"入库量数据。仅修改 app.py 一处。
todos:
  - id: strip-any-in-stock
    content: 在 app.py 的 get_diesel() 函数中，返回数据前剥离每条记录的 any_in_stock 字段，确保前端完全不接触该入库数据
    status: completed
---

## 用户需求

在柴油统计报表的UI展示界面中，完全忽略并隐藏"Any in Stock？"字段。该字段代表的是入库的柴油量，而非实际消耗的柴油量。为确保数据准确性与用户理解，报表展示应仅保留并突出真实的柴油消耗量数据，避免将入库量与消耗量混淆。

## 核心功能

- `/diesel` API 返回的 JSON 数据中不再包含 `any_in_stock` 字段，前端完全无法接触该入库数据
- 前端柴油页面（仅含"消耗趋势"和"设备占比"两个图表）继续正常展示 generator/compressor/bajaji/pickup/dump_truck 五个消耗量字段
- parser.py 保留 `any_in_stock` 的原始解析能力（内部需要时可恢复）
- 两处 Excel 导出原本就已跳过 `any_in_stock`，无需修改

## 技术方案

### 修改文件

仅修改 `app.py` 一个文件，不改动 parser.py 和 index.html。

### 修改位置

`app.py` 第 735-737 行，`get_diesel()` 函数：

```python
# 当前代码
@app.route('/diesel', methods=['GET'])
def get_diesel():
    md = APP_STATE.get('main_data', {})
    return jsonify(md.get('diesel_data', []))
```

改为：

```python
@app.route('/diesel', methods=['GET'])
def get_diesel():
    md = APP_STATE.get('main_data', {})
    data = md.get('diesel_data', [])
    # 剥离 any_in_stock（入库量），UI 仅展示消耗量
    return jsonify([{k: v for k, v in d.items() if k != 'any_in_stock'} for d in data])
```

### 关键决策

- **为何在 API 层剥离而非前端过滤**：前端隐藏只是"视而不见"，数据仍在网络传输中；API 层剥离是"源头切断"，更彻底
- **为何保留 parser.py 不改**：parser 负责数据解析的完整性，保留 `any_in_stock` 为将来可能的内部数据分析留余地；且改 parser 需联动多处（导出中的字段映射等），风险更大
- **为何不改 index.html**：前端当前已无 `any_in_stock` 的渲染逻辑，无需修改

### 影响分析

- 不影响 parser.py 的数据解析与存储
- 不影响 `/diesel` 以外的任何 API
- 不影响两处 Excel 导出（原本就跳过了该字段）
- 不影响前端柴油图表的渲染（前端只使用 5 个设备消耗字段）