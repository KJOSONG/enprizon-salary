# 组织架构重组方案（2026-11，生产库核实版 v2）

> **✅ 已实施完毕（2026-10-25，实施记录见文末 §八）**

> 依据 2026-10-25 截图组织架构图 + 用户确认事项制定。
> **数据来源：生产库只读查询**（`ssh -p 22222 -i ~/.ssh/new.pem root@47.236.187.33`，
> `sqlite3 'file:/root/enprizon-salary/data/kilwa.db?mode=ro'`，查询时间 2026-10-25）。
> ⚠️ 本地 `data/kilwa.db` 是 10-22 的滞后快照，**禁止作为审计依据**（v1 方案曾误用，已作废重写）。
> 铁律：历史月份薪资结果逐分不变；计件员工调岗的类型切换配置必须先于数据迁移上线。

---

## 〇、生产端现状与目标的差距（2026-10-25 实测，在册 146 人）

生产端已**自行完成**了部分整合，本次方案只做剩余增量，已完成的绝不重复操作：

| 已提前完成（勿动） | 证据 |
|---|---|
| Mechanic Team → `Engineering & Maintenance Department` 全员改名 | 生产库 20 人已全部挂新部门名 |
| LAMEKI HARUNA KASEMA（127）姓名已正确、在工程部 | id=127 实测 |
| RAJABU MOHAMED RAJABU 已改名且转月薪 | id=168，monthly |
| 井下第 4 班组 AYI XIBA 已建 | employee_groups id=4 |
| 10 月新增员工/调岗/类型调整（Sorter 批量入职、AZIZI 转破碎计件、SHAFI OMARY 转月薪入 LGP 等） | employee_events 488-520 |

**仍需迁移的增量**：井下部门改名、三主管归采矿部、后勤两部门并站点运营、两名加油员+LAMEKI 调动、分拣/破碎两子部门改名、EKON 调任。

---

## 一、目标架构与系统映射模型

### 1.1 目标组织树（截图口径）

```
MINE SITE MANAGEMENT (Site Manager)
├── Mining Department（部长 Rickson Richard Mollel，留 ENPRIZON LINDI PROJECT）
│   ├── Mining Department（叶子：三名主管，见 1.3）
│   ├── Production TEAM（原 Production TEAM （underground） 改名，去掉 "(underground)"）
│   │     班组：LAMBA / SAKA / MIZOZO / AYI XIBA（均已建）
│   └── Driller Team（不变，挂到采矿部名下）
├── Engineering & Maintenance Department（部长 LAMEKI HARUNA KASEMA=127，调入 ENPRIZON LINDI PROJECT）
│     主管：RAJABU MOHAMED RAJABU（id=168，monthly，已就位）
├── Site Operations & Services Department（部长 Peter Michael Gama，留 ENPRIZON LINDI PROJECT）
│     ← Logistics + Logistics/Ground production（余员）+ 两名加油员
└── Materials & Logistics Department（部长 BARAKA JULIAS，留 ENPRIZON LINDI PROJECT）
    ├── Sorting Team（原 Sort Crush 改名）主管 GASPER IBRAHIMU
    └── Crushing Team（原 Sort Crush/Crush Piece Rate 改名）主管 EKON LEONARD（82，需从 Sort Crush 调入）
```

### 1.2 系统映射模型（关键设计决策）

系统 `employees.department` 是**扁平字符串**，全链路（计算、采集、调岗、筛选）按规范化
（去空格/全角括号转半角/大写）比较。本次**不引入层级字段**：

- **员工只挂叶子部门字符串**；父子关系仅存在于组织图展示层，后续如需按大部门
  分组显示，用 settings 表加一个 JSON 映射即可（本期不实现 UI）。
- **迁移后的全部叶子部门取值**（生产库 146 人逐一归属）：

| 部门字符串 | 归属大部门 | 人数 / 薪资类型构成 |
|---|---|---|
| `Production TEAM` | Mining | 24 · piece_underground |
| `Driller Team` | Mining | 12 · piece_driller |
| `Mining Department` | Mining | 3 · monthly×2 + day_rate×1（三主管叶子，见 1.3） |
| `Engineering & Maintenance Department` | Engineering | 17 · day_rate 9 + monthly 8 |
| `Site Operations & Services Department` | Site Ops | 26 · day_rate 14 + monthly 12 |
| `Sorting Team` | Materials & Logistics | 33 · day_rate 24 + monthly 9 |
| `Crushing Team` | Materials & Logistics | 15 · piece_crush 10 + day_rate 5 |
| `RIG` | （本期不动） | 7 · day_rate |
| `ENPRIZON LINDI PROJECT` | 站点管理层 | 9 · day_rate 7 + monthly 2 |

合计校验：24+12+3+17+26+33+15+7+9 = **146** = 生产端在册人数 ✔

### 1.3 三名主管为什么单独落 `Mining Department` 叶子（用户已确认归采矿部）

截图把三主管画在 Production TEAM 框内，但**技术上报管制**决定了不能挂 `Production TEAM`：

- 井下出勤采集按 `部门=井下 ∧ team_id=班组` 取花名册；主管无班组（team_id=0），
  挂 `Production TEAM` 会从所有班组花名册和"其他部门出勤采集"池**同时消失**，
  月薪工的 A/L 假勤标记断链 → 月薪扣款出错。
- 挂 `Mining Department` 叶子：不含井下/钻工/破碎关键词 → 继续留在"其他部门"
  出勤采集池（与今天在 Logistics/Ground production 的行为完全一致），且
  调岗表单选它时按"非计件目标"处理，审批人显式确认类型与基数 —— 与现有
  P35-B5 确认层天然吻合。
- 类型事实（用户已裁决 RUPIMO 保持日薪）：采矿部实际含 **四种** 薪资类型——
  井下计件(24) / 钻工计件(12) / 月薪(2 主管) / 日薪(1 主管 RUPIMO)。方案按四类配置，
  不因"三种"表述而隐藏日薪分支。

---

## 二、人员迁移映射总表（生产库 146 人，逐一对齐）

| # | 动作 | 人数 | 薪资类型处理 | 明细 |
|---|---|---|---|---|
| 1 | `Production TEAM （underground）` → `Production TEAM` | 24 | **不变**（piece_underground） | 仅部门改名；team_id 1/2/3/4（AYI XIBA）不动 |
| 2 | `Driller Team` | 12 | 不变 | 无操作，组织上挂采矿部 |
| 3 | id 25 ADHIRUDINI SIJAE RASHID、id 52 YUSUPH HAMISI MTWIKU（均 monthly SUPERVISOR）、id 30 RUPIMO MASAGA KADOSHI（day_rate）：`Logistics/Ground production` → `Mining Department` | 3 | **不变** | team_id=0；改部门不改类型，无需 override |
| 4 | `Logistics` 全员 → `Site Operations & Services Department` | 14 | 不变（9 day + 5 monthly） | |
| 5 | `Logistics/Ground production` 余员 → `Site Operations & Services Department` | 10 | 不变（5 day + 5 monthly） | 三主管移出后剩余：71/75/74/83/77 + 72/36/76/172/106 |
| 6 | id 118 JORAM JACOB NYANGORO、id 126 RAMAZANI MASAME：`Engineering & Maintenance Department` → `Site Operations & Services Department` | 2 | 不变（day_rate，加油员） | |
| 7 | id 127 LAMEKI HARUNA KASEMA：`Engineering & Maintenance Department` → `ENPRIZON LINDI PROJECT` | 1 | 不变（day_rate） | 工程部部长，与其他三部长同挂站点管理层；无需改名（生产端姓名已正确） |
| 8 | `Sort Crush` → `Sorting Team` | 33 | 不变（24 day + 9 monthly） | EKON 移出后余员；GASPER(84) 留任主管 |
| 9 | `Sort Crush/Crush Piece Rate` → `Crushing Team` | 14 | 不变（4 day + 10 piece_crush） | 含 AZIZI SWALEH(29) 等新计件成员 |
| 10 | id 82 EKON LEONARD：`Sort Crush` → `Crushing Team` | 1 | 不变（day_rate） | **易漏点**：截图任命其为破碎主管，现库在 Sort Crush |
| 11 | `RIG` | 7 | 不动 | 用户裁决维持现状 |
| 12 | `ENPRIZON LINDI PROJECT` 原有 8 人（含 Rickson/Peter/Baraka 三部长） | 8 | 不动 | + LAMEKI 后共 9 人 |

合计校验：9+3+24+12+17+26+33+15+7 = **146** ✔
（Site Ops = 14+10+2 = 26；Engineering = 20−3 = 17；Sorting = 34−1 = 33；Crushing = 14+1 = 15）

**执行注意**：迁移脚本运行当天必须重新从生产库拉取名单（10 月人员变动频繁，
上表 id/人数以 2026-10-25 快照为准，若执行日有新入职/调岗，按"部门字符串映射"原则
套用而非按 id 硬编码）。

---

## 三、计件员工调岗的薪资类型配置（本次需求核心）

### 3.1 现有机制（保留，不改语义）

- **调入计件部门自动切计件**：`apply_approved_event`（core/database.py:1882-2009）
  按新部门名自动判定 `piece_driller / piece_underground / piece_crush`，
  落 `eff → 9999-12-31` 哨兵 override，清 day_rate/monthly_salary 基数，写台账。
- **跨计件/非计件调岗显式确认**（P35-B5，app.py:3054-3093）：转出计件或调入
  非计件部门时，审批人必须在确认层选新类型；选 day_rate/monthly 必须填基数
  （>0 强校验），否则 400。
- **调岗回收旧哨兵覆盖**（database.py:1976-1989）：生效日前旧覆盖保留保历史薪资，
  生效日起新状态接管 —— 历史月逐分不变的法律保障，不动。
- **日粒度时间线**（P35 `_build_transfer_day_map` + calculator `_dept_at/_type_at`）：
  调岗生效日切分部门/班组/类型，生效日前按旧轨计薪。
- 生产端 10 月已多次实战验证该机制（事件 509/519/520 等）。

### 3.2 必须修改的三处"部门→类型"配置点（新部门名注册）

| 位置 | 现值 | 改为 |
|---|---|---|
| core/database.py:1885-1889 | `is_ug = _nd=='PRODUCTIONTEAM(UNDERGROUND)'`；`is_crush = _nd=='SORTCRUSH/CRUSHPIECERATE'` | `is_ug = _nd in ('PRODUCTIONTEAM','PRODUCTIONTEAM(UNDERGROUND)')`；`is_crush = _nd in ('CRUSHINGTEAM','SORTCRUSH/CRUSHPIECERATE')`（is_driller 不变） |
| app.py:3081-3083（调岗免确认白名单） | `('PRODUCTIONTEAM(UNDERGROUND)','SORTCRUSH/CRUSHPIECERATE')` | `('PRODUCTIONTEAM','PRODUCTIONTEAM(UNDERGROUND)','CRUSHINGTEAM','SORTCRUSH/CRUSHPIECERATE')` |
| 前端确认层/表单联动（index.html:7349-7370、8468-8481、4135-4152、4872-4890、4976-4990、5173；mobile.html:1216-1217、1594-1613、3122-3148） | 关键词/裸名比较 | 统一改"规范化双名集合"判断（见 4.1），禁新增裸字符串比较 |

### 3.3 重组后调岗-薪资类型矩阵（今后照此执行）

| 目标部门 | 类型行为 | 附加要求 |
|---|---|---|
| `Production TEAM` | 自动 → piece_underground，**免确认** | 必选班组（LAMBA/SAKA/MIZOZO/AYI XIBA） |
| `Driller Team` | 自动 → piece_driller，**免确认** | 必选队长 |
| `Crushing Team` | 自动 → piece_crush，**免确认** | 无班组 |
| `Mining Department` | 非计件目标 → 审批确认层选 monthly/day_rate + 基数 | 主管调入走此路径 |
| `Engineering & Maintenance Department` / `Site Operations & Services Department` / `Sorting Team` / `RIG` / `ENPRIZON LINDI PROJECT` | 非计件目标 → 审批确认层（转出计件默认日薪） | day_rate/monthly 必填基数 |
| 计件部门之间互转（如井下↔钻工） | 自动切新计件轨，免确认 | 各自班组/队长要求照旧 |

**表单铁律提醒**：调岗审批确认层的类型下拉延续"空选 + 请选择 + 强校验"规则
（2026-09-08 用户铁律），不得预填默认值；仅"转出计件默认日薪"这一既有例外保留。

### 3.4 本次重组为什么不走 OA 调岗流程

146 人 bulk 改部门若逐个走 OA：24 名井下员工"改名不换部门语义"也会触发
确认层与哨兵 override 重写，产生上百条事件与大量无意义 override 变更，
反而把计件台账搅乱。故本次用**一次性迁移脚本直改 employees.department**
（逐人写 audit_log，`action='org_restructure'`，含 old/new 部门），类型与基数零改动、
override 零改动 —— 计件历史台账天然不动。**今后个人调岗一律仍走 OA。**

---

## 四、代码改动清单（先上线，后迁数据）

### 4.1 前端：关键词匹配 → 规范化集合匹配（破坏性风险最高的一处）

现状用 `includes('UNDERGROUND')` / `includes('CRUSH PIECE RATE')` 判池
（index.html:8563-8572、mobile.html:1803-1817）。`Production TEAM` 新名**不含
UNDERGROUND**、`Crushing Team` **不含 CRUSH PIECE RATE**，且 `Crushing Team`
含 "CRUSH" 若误用宽关键词会把破碎队错进出勤采集池。统一改为：

```js
// 两端模板各放一份（index.html / mobile.html，内联 JS 无法共享模块）
const _UG_DEPTS  = ['PRODUCTIONTEAM', 'PRODUCTIONTEAM(UNDERGROUND)'];        // 双名兼容历史
const _CR_DEPTS  = ['CRUSHINGTEAM', 'SORTCRUSH/CRUSHPIECERATE'];
const _DR_DEPTS  = ['DRILLERTEAM'];
const normDept = d => (d||'').replace(/\s+/g,'').replace(/（/g,'(').replace(/）/g,')').toUpperCase();
const isUgDept = d => _UG_DEPTS.includes(normDept(d));
const isCrDept = d => _CR_DEPTS.includes(normDept(d));
const isDrDept = d => _DR_DEPTS.includes(normDept(d));
// 'other'（出勤采集池）= !isUg && !isDr && !isCr —— Sorting/Mining/SiteOps/Engineering/RIG 均落入
```

替换点：`filterEmpByDept`/`deptPool` 四分支、UG_DEPT 常量（mobile.html 2633-2756
共 6 处 → 改 `'Production TEAM'`）、调岗/入职/员工编辑的班组联动（4135/4872/4976/
5173/8366/8468 与 mobile 3122-3148）、采集历史部门筛选（8592、8697、9665-9678
`ugDeptExact` → 推送新名）、9717/9740/9811/9828/9838、mobile 1969。

### 4.2 后端 Python

| 文件:行 | 改动 |
|---|---|
| app.py:3897-3904 | `_UG_NORM_TARGET` 改为集合 `{'PRODUCTIONTEAM','PRODUCTIONTEAM(UNDERGROUND)'}`，`_is_ug_dept` 改 in 判断（17 处调用自动生效） |
| core/calculator.py:20,173,226,1334,1378,1864,1905 | `PRODUCTION_UG_DEPT` 增加伴随常量 `_UG_DEPT_SET`（双名），比较改 in；**历史 dept_day_map 旧名必须继续命中** |
| core/database.py:1885-1889, 3539 | 见 3.2；3539 班组白名单加 `'PRODUCTIONTEAM'` |
| core/addressbook.py:10-15 | DEPT_PATTERNS：piece_underground 增 `'Production TEAM'`；day_rate 增 `'Sorting Team'`（'Sort Crush' 等旧模式保留兼容旧通讯录） |
| static/js/i18n.js:979,2343 | `transfer_piece_hint` 文案：破碎括注改 `Crushing Team` |
| AGENTS.md:639 | "前端陷阱"注记更新为新名 + 双名集合规则 |
| docs/P28_LEAVE_RULES_SPEC.md:196,493 | 判定口径补双名说明（文档同步） |

### 4.3 不改的部分（明确列出防误伤）

- 五轨计算引擎逐日选轨、per_date_type、哨兵 override 语义 —— 零改动。
- collection_submissions 历史行（旧部门名）—— 不迁移，展示与重算靠双名兼容。
- employee_base_history —— 部门列仅记录用，本次不回填。
- permissions/OA/评分/NSSF —— 均不按部门名判定。

---

## 五、数据迁移方案（生产库一次性脚本）

前置：代码已上线（双名兼容期，新旧名都识别，先发码后迁数零风险）。

1. **备份（在生产服务器上）**：
   `cp /root/enprizon-salary/data/kilwa.db /root/enprizon-salary/data/backups/kilwa_before_orgrestructure_YYYYMMDD.db`
   （沿用 backup.sh 的部署前安全备份约定）。
2. **迁移脚本**（_work/org-restructure/migrate.py，本地写好 → scp 上服务器执行一次）：
   - 按第二节映射表执行，**部门字符串映射优先**（`UPDATE employees SET department=? WHERE department=?`），
     人级移动（25/52/30/118/126/127/82）按 id 精确 UPDATE；
   - 执行前先重拉生产名单核对人数（146 基准 + 当日增量）；
   - 主管三人确认 `team_id=0`；
   - 逐人 INSERT audit_log（action=`org_restructure`，old/new 部门+操作者）；
   - 幂等：先查当前部门已是目标值则跳过，可安全重跑。
3. **生效日期**：默认 **2026-11-01 前的低峰时段执行**。理由：dept 字符串只影响
   出勤采集路由与调岗流程，10 月已采集数据按 eid 计薪不受影响，但月度切换执行
   最干净，10 月账完全落在旧架构口径上。若需提前，10 月内执行亦安全（见 4.3）。
4. **不执行的动作**：不建 OA 事件、不写 overrides、不动 team_id/队长表、
   不迁移历史 collection 行、不重复执行生产端已完成的改名（见第〇节）。

---

## 六、测试与验收

### 6.1 单测（pytest，隔离副本库）

- 调岗自动映射：新名 `Production TEAM`/`Crushing Team` 审批 → piece 哨兵 + 基数清零；
  旧名 payload 兼容回归（tests/test_oa_transfer_captain.py 扩展双名用例）。
- `Mining Department` 调岗 → 触发确认层（transfer_salary_type_required 400 路径）
  + monthly 必填基数。
- 计算双名兼容：构造 dept_day_map 携带旧名的历史员工，scoring/v2 两模式下
  UG 判定不回归。
- 'other' 出勤池：`Mining Department`/`Sorting Team` 成员在池内，
  `Crushing Team` 成员在池外。

### 6.2 生产验收清单（迁移后当场执行）

1. 10 月薪资页总额与迁移前快照**逐分一致**（重点抽 24 名井下、10 名破碎计件）。
2. 移动端/桌面采集：井下按班组出勤（LAMBA/SAKA/MIZOZO/AYI XIBA 名单合计 24 人）、
   钻工按队长、破碎表单池 = Crushing Team 15 人、出勤"其他"池含
   Mining Department 三主管 + Sorting Team 33 人。
3. 调岗试单（测试员工）：转 `Crushing Team` 免确认自动 piece_crush；
   转 `Mining Department` 弹确认层。
4. 员工页部门筛选、工资条按部门导出（含新部门名，路径含 `&` 不炸）。
5. 生产库抽查：`SELECT department, COUNT(*) FROM employees WHERE status='active'
   GROUP BY department` 与 1.2 表逐行相等（146 人）。

### 6.3 回滚

在生产服务器恢复 6.1 前置备份 + git revert 代码提交即可；双名兼容保证旧名库在新代码下同样运行，
回滚无窗口期。

---

## 七、遗留事项

| 事项 | 处理 |
|---|---|
| 井下第 4 班组 | **已解决**：生产端已建 AYI XIBA（employee_groups id=4） |
| RIG 7 人 | 维持现状（成员较 9 月有进有出：+ADWAD(171)/AMOURY(175)），后续归属明确后单独走 OA 调岗 |
| 大部门分组展示（四部父子层级 UI） | 待需求提出后用 settings JSON + 前端分组实现 |
| 采矿部类型口径 | 系统按四种类型配置（含 RUPIMO 日薪）；与"三种"表述的差异已在 1.3 说明 |
| 本地库快照滞后 | 建议迁移执行前用生产库刷新本地 `data/kilwa.db`，保证本地测试环境与生产一致 |
| `_build_ug_team_members` 不过滤 dismissed | **历史既有行为**（迁移前后映射完全一致，非本次引入）：24 ABEDI（10-01 离职）、41 JOSEPH（09-04 离职）仍以旧部门名+班组出现在班组映射中。如需修复另行立项（注意：修复会改变 11 月起班组花名册构成，需用户确认） |

---

## 八、实施记录（2026-10-25）

1. **代码**：commit `5e9db5a`（双名兼容 + 新名注册 + 前端谓词化），39/39 pytest 通过，push → 服务器 `git pull` + 重启，`_UG_DEPT_SET` 生产端验证生效。
2. **备份**：`data/backups/kilwa_before_orgrestructure_20261024.db`（服务器本地时间 10-24 = EAT 10-25）。
3. **迁移**：`scripts/migrate_org_restructure.py`（幂等）——7 人级调动 + 5 组 bulk 改名共 **102 条变更**，逐人 audit_log（action=`org_restructure`）。迁移后分布与 §1.2 预期**逐行一致**（146 人），旧部门名残留 0。
4. **历史月薪资一致性**：同代码分别跑迁移前备份库 vs 迁移后库——
   - 2026-10：157 人逐人逐项 **0 差异**
   - 2026-09：168 人 **0 差异**；2026-08：182 人 **0 差异**
   - 过程中发现并修复一处：127 LAMEKI（永久 monthly 750000）调入 `ENPRIZON LINDI PROJECT` 会从 10 月起触发"顶层月薪满勤 1-26"特判（+115,385）。修复 = 补月度基线（2026-01=工程部旧口径 / 2026-11=ENPRIZON 新口径），10 月回归旧口径，**11 月起新口径生效**（audit: `org_restructure_baseline`）。
5. **基线校正**：29/47/50/177 四人 2026-11 基线按现部门补齐（audit: `org_restructure_baseline_fix`；不影响 11 月前任何月份）。
6. **班组映射核验**：2026-11 UG 班组映射 {LAMBA:8, SAKA:9, MIZOZO:7} + 2 名已离职成员（既有行为，见 §七），现役 24 人全部在册无遗漏。
7. **验收工具**：`scripts/verify_salary_identity.py`（对任意 DB 跑指定月管线输出逐人 JSON，可复用于今后调岗/迁移的前后对比）。

---

## 九、M&L 部门级主管叶子（2026-10-26 增量，用户确认）

组织图更新：Materials & Logistics Department 与 Mining Department 同构，增设**部门级主管叶子**
`Materials & Logistics Department`（下拉显示「主管」），两名主管按采矿部三主管模式管理
Sorting/Crushing 两队（team_id=0，出勤归「其他部门」池）：

| id | 姓名 | 原部门 | 新部门 | position | 类型 |
|---|---|---|---|---|---|
| 84 | GASPER IBRAHIMU | Sorting Team | `Materials & Logistics Department` | supervisor-sorting（已有） | day_rate（月基数 500000 override，不动） |
| 90 | MALIKI HARUNI | Sorting Team | `Materials & Logistics Department` | 补记 supervisor-crush | day_rate（12000 override，不动） |

**背景**：EKON LEONARD(82) 已由生产端 OA 事件 535 批准转 `Production TEAM`（member，team 4，
2026-10-26 生效），破碎主管席位空出；MALIKI 10-25 的调岗申请（事件 541）误选
`Site Operations & Services Department` 被拒，本次按组织图直接归位。

**实施**（2026-10-26）：
1. 代码先行：`scripts/migrate_ml_supervisors.py`（幂等）入库；DEPT_TREE（index/mobile 各一份）
   M&L 组增加主管叶子；`tests/test_org_restructure.py` 补 M&L 叶子调岗用例（非计件目标、
   不自动切类型、team_id 归 0）。
2. 数据：生产库执行迁移（2 条变更 + 逐人 audit_log `org_restructure`）；迁移后分布
   Sorting 23 / Crushing 14 / M&L 叶子 2（Production TEAM 32 等为 10-25 晚批量调岗后现状，
   与 §1.2 的差异属生产端自然演进，非本次引入）。
3. 验收：迁移前后备份库 vs 生产库跑 2026-10 管线逐人对比（两名主管均在「其他部门」池内、
   类型零改动）——0 差异；前端两级下拉 M&L 组显示「Sorting Team / Crushing Team / 主管」。
