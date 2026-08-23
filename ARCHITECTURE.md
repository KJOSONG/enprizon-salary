# ENPRIZON LINDI PROJECT — 薪资系统架构文档

> **历史快照**（v3.0 重构架构决策）。现行需求与产品定义见 `REFACTOR_SPEC.md` v4。
> 精简版 | 最后更新: 2026-08-23 | 维护者: KEJU
> 原则: 只写设计决策和理由，不写代码细节（代码会变，理由不变）

---

## 一、项目定位

Web 薪资计算系统。用户上传 Excel 考勤数据 -> 自动解析 -> 五轨薪资计算 -> 可编辑出勤、例外覆盖 -> Web 页面展示。

部署在阿里云新加坡服务器 (47.236.187.33)，Flask + gunicorn + Nginx 反代。

---

## 二、数据流水线

```
Attendancedatadailyandpiecerate.xlsx --+
ENPRIZON_LINDI_PROJECT.xlsx ----------+
                                       v
  parser.py --> namematch.py --> calculator.py --> app.py (API) --> 前端六页面
                    |                  |
            通讯录索引加载      逐日单轨合并
            employee_id 生成    总表 + 日明细
```

### 2.1 输入文件

| 文件 | 内容 | 说明 |
|------|------|------|
| Attendancedatadailyandpiecerate.xlsx | 产量 + 出勤 | 主文件, Sheet1=产量(D/N队+钻工), Sheet2=日薪出勤 |
| ENPRIZON_LINDI_PROJECT.xlsx | 通讯录 | 134人, 含部门和账号, 作为员工身份基准 |
| 预支汇总数据.xlsx | 预支记录 | 可选 |

### 2.2 姓名标准化 (namematch.py)

**核心决策**: make_employee_id(name) 优先从通讯录索引查找, 返回**通讯录账号**(如 111, 128, 005), 而非旧版的姓名字符串。

匹配链路:
1. 输入姓名 -> 去括号/去空格/大写 -> 查 _AB_INDEX (通讯录索引表)
2. 未匹配 -> 查 _LEGACY_CANONICAL (短名->全名回退表) -> 再查通讯录
3. 仍未匹配 -> 回退到姓名去空格大写 (兼容离职/通讯录外人员)

通讯录匹配失败的人 (如已离职 ABUUMUSSA) 会走回退路径, employee_id 仍为旧格式。
display_name 优先用通讯录中的别名列, 无别名则用去括号的姓名。

---

## 三、薪资计算引擎 (calculator.py)

### 3.1 轨道定义

| 轨道 | 数据源 | 计薪逻辑 |
|------|--------|----------|
| 井下计件 | shift_production (白/夜班) | 当日产量 * 单价 / 出勤人数, 人均平分 |
| 钻工计件 | driller_production (队长制) | 当日产量 * 单价 / (队员+1队长份额), 队长*2份额 |
| 破碎计件 | CRUSH TEAM 文件 | bags * 300 TZS / 有效人数, 同日多条记录独立均分 |
| 日薪 | attendance | 日薪基数 * 出勤天数 |
| 月薪 | employees.monthly_salary | 月薪基数 - A/L天数比例扣减 |

### 3.2 逐日单轨模式 (v3.0 核心重构)

**旧架构**: 员工可能有多个 has_date_range 日期区间, 每个区间可能对应不同轨道, 叠加计算后合并, 逻辑复杂/易出双重计薪 bug。

**新架构 (e6b9487)**:
1. 构建 per_date_type[eid][date] - 统一的逐日类型映射, 将所有临时例外展开为逐日数组
2. 五轨各自独立计算, 产生 ug_daily / driller_daily / crush_daily / day_salary / monthly_salary
3. **逐日合并**: 对每个员工的每一天, 按 per_date_type 或永久类型选**一个**轨道取值求和
4. 任一日期**只归属一个轨道**, 从根本上杜绝双重计薪

**关键推理**:
- 永久覆盖 (start_date 和 end_date 都为空) -> 改变 effective_type, 覆盖整月的默认轨道
- 临时例外 (有日期区间) -> 只影响区间内的轨道选择, 不影响 salary_type 标签
- 日薪/月薪轨道不产生每日产出 (不用 ug_daily/driller_daily), 在合并阶段直接取日薪/月薪计算结果
- 破碎计件轨道 (crush_daily) 独立计算, 同日多条破碎记录各自均分, 合并阶段同样只取一个轨道

### 3.3 日工资明细 (compute_daily_breakdown)

与 calculate_all 共用相同的 per_date_type + 四轨子函数结果, 按相同的逐日选轨逻辑生成 {员工: {日期: 金额}} 明细。
前端"日工资"页面和薪资页应发金额**必须一致** (总则要求)。

---

## 四、例外覆盖系统

### 4.1 overrides 表设计

| 字段 | 用途 |
|------|------|
| employee_id | 通讯录账号 |
| salary_type | piece_underground / piece_driller / day_rate / monthly |
| day_rate / monthly_salary | 覆盖的薪��基数 |
| start_date / end_date | 空=永久覆盖, 非空=临时例外 |
| shift | 井下计件班次 D/N |
| captain | 钻工队长名 |

### 4.2 覆盖类型判断

```
start_date 为空 AND end_date 为空 -> 永久覆盖 (改变整月 effective_type)
start_date 非空 OR end_date 非空 -> 临时例外 (只影响日期区间内轨道选择)
```

临时例外中, shift 字段用于井下计件的 shift_adds (手动加入计件分配)。

### 4.3 attendance_overrides 表

(employee_id, date) 联合主键, status 为 P/A/L。
A/L 标记的员工从当日计件分配中排除 (按日重新均分, 总额守恒)。

---

## 五、出勤与产量核对

### 5.1 双路径核对 (verification.py)

- **路径一**: 产量 * 单价, 按日求和 (理论总额)
- **路径二**: 薪资计算结果中各轨道求和 (实际分配总额)

差异 |diff| <= 10 视为浮点舍入误差, > 10 高亮标红。
目前井下轨道存在差异 ~156,000 (5/25 夜班无员工名单, 产量无人领取), 钻工轨道一致。

### 5.2 A/L 对计件的级联影响

出勤页标记 A/L -> 写入 attendance_overrides -> trigger recalculate() -> 员工从当日计件分配排除 -> 剩余人员平分当日产量。**总额不变** (队长 A/L + 0队员的极端情况除外)。

---

## 六、数据库概览

| 表 | 记录数 (~) | 用途 |
|----|-----------|------|
| overrides | 146 | 薪资例外/覆盖 (永久+临时) |
| attendance_overrides | 200 | 出勤手动标记 |
| employees | 45 | 员工信息缓存 |
| monthly_data | 263 | 月度数据快照 |
| bonus_penalties | 10 | 奖惩记录 |
| audit_log | ~1213 | 操作审计 (UTC+3 时区) |
| settings | * | 系统配置 (单价等) |

**关键变更 (2026-06-30)**: 全部表 employee_id 从旧格式 (name-based) 迁移为通讯录账号。

---

## 七、前端六页面联动

```
+---------------------------------------------------+
|  数据台(Dashboard) - 产量趋势图 + 日工资分布图      |
|  员工页  - 例外管理 (永久/临时) + NSSF 开关         |
|    | 保存后自动 recalculate()                       |
|    v                                                |
|  出勤页  - 点击格子 toggle P/A/L                    |
|    | 自动 recalculate() + reload                    |
|    v                                                |
|  薪资页  - 总表五轨 + 核对面板 + 日工资明细         |
|          - 产量图表 + 导出 Excel                    |
|  日工资明细页 / 系统配置页(审计/上传/定价/权限)     |
+---------------------------------------------------+
```

---

## 八、部署

| 组件 | 配置 |
|------|------|
| 应用 | Flask + gunicorn, 监听 127.0.0.1:8081, 1 worker 2 threads, 120s timeout |
| Web 服务 | Nginx 反代 /salary/ -> 8081 |
| 数据库 | SQLite (WAL 模式), data/kilwa.db |
| 时区 | 整体 UTC+3 (坦桑尼亚), 仅 audit_log 强制 UTC+3 |
| systemd | enprizon-salary service |

**部署命令**: save-salary "msg" -> git commit + push + systemctl restart (一步完成)

---

## 九、已知数据边界

1. **5/25 夜班产量无人领取**: 产量 156,000 但源数据缺员工名单 -> path1/path2 永久差异
2. **钻工 5/1-5**: 部分队伍无成员 -> 仅队长 1 人
3. **同名多槽位**: 同队长同天多次出现 -> 产量合并/成员去重
4. **跨 Sheet 人员**: 同时出现在产量表和日薪表 -> 需手动指定类型
5. **预支但不在主表**: 通讯录外人员 -> 单独列出

---

## 十、代码分工速查

| 文件 | 职责 |
|------|------|
| app.py | Flask 路由 + 认证 + 会话 |
| core/parser.py | Excel 解析 (3 Sheet -> 结构化数据) |
| core/namematch.py | 姓名标准化 + employee_id 生成 + 员工主列表 |
| core/calculator.py | 五轨计算 + 逐日单轨合并 + 日明细 |
| core/database.py | SQLite ORM + 审计日志 |
| core/verification.py | 双路径核对 + 逐日对比 |
| core/exceptions.py | 例外覆盖标记加载 (兼容 JSON + DB) |
| core/advance.py | 预支数据解析 |
| core/addressbook.py | 通讯录 Excel 解析 |
| core/pricing.py | 单价配置 |
| templates/index.html | 单页 SPA (约 2621 行, 6 页面标签, 全部 JS 内联) |

---

## 十一、权限体系 (P18 框架 -> P29 V2.1 重造)

> P29 已实施于 `feature/p29-permission-v2` 分支 (本地验证通过, 待部署)。需求权威见 `docs/P29_PERMISSION_V2_SPEC.md`。

### 11.1 目录为什么重造 (核心决策: 目录 = 页面)

P18 的目录按功能域划分, 出现过 production:* 这类数据域键, 与前端页面对不上: 有键无页面, 授权时要在"键"和"页面"之间做心算翻译。V2.1 改为**目录 = 页面**: 21 键 / 8 模块 (数据台/员工/审批中心/出勤/薪资/数据采集/评分/系统), 一个模块对应一个侧边栏入口, 权限编辑器矩阵按侧边栏顺序分组。

production:* 移除后的去向: 查看 -> dashboard:view, 编辑 -> collection:view + 4 个表单键 (underground/driller/crush/attendance)。

### 11.2 动作语义 (四类)

| 动作 | 语义 | 例子 |
|------|------|------|
| view | 看得到页面 / 读得到数据 | salary:view |
| 操作键 | 页面内的具体写操作 | oa:approve, employees:edit, attendance:export |
| apply | 提交 OA 申请 (申请人视角) | oa:apply |
| manage | 管理角色与授权本身 | system:manage |

apply 与 approve 分离是重造动机之一: 采集工/普通员工要能提加班/请假申请, 但不该有任何审批权。

### 11.3 内置角色与继承决策

| 角色 | 预设 |
|------|------|
| super_admin | *:* |
| admin | 全模块管理 |
| collector | 仅数据采集 4 表单键 |
| applicant | oa:view + oa:apply, 只看自己的提交 |
| viewer | 全模块 view (含薪资只读) |

- **字面继承**: ROLE_HIERARCHY = {'collector': ['applicant']}, collector 直接继承 applicant 的全部键 (能采集必然要能交申请)。不做通用层级推导; custom 角色完全平级, 不参与继承。
- **editor 降级**: editor 移出内置角色 (旧语义与新五角色定位冲突), 但 ROLE_LEVELS['editor'] = 1 保留。理由: 存量装饰器基线 (@editor_required 等) 仍引用该层级, 删掉会破坏兼容。

### 11.4 三表迁移 (_migrate_permissions_v2)

挂在两条启动路径上执行, 幂等靠 settings 表 perm_v2_migrated = 1 标志:

1. **备份先行**: 旧 permissions / role_permissions / user_grants 全量写入 audit_log (action='p29_migration_backup')
2. **重置**: permissions 注册表刷成 V2.1 目录, 内置角色 role_permissions 刷成新预设
3. **翻译**: 存量 user_grants 里的 production 旧键映射到新键; deny 类授权复制到全部 5 个替代键 (拒绝语义不松动)

**回滚 = 恢复 P29 之前的 DB 快照**, 没有代码级回滚开关; audit_log 备份用于审计追溯, 不做自动还原。

### 11.5 动态表单键门控 (约定)

采集端点统一约定: @login_required 进门 + handler 内按 payload 表单类型动态 check_permission(u, 'collection', <type>)。不挂静态角色地板, 理由: collector 是 0 级角色, 任何 editor 地板都会让 collector 人设失效; 表单类型与动作名天然对齐, 加表单即加键, 无需改装饰器。

OA 同构: 申请三端点 (POST /api/oa/events, /api/oa/leave, /api/leave/sick) 挂 oa:apply; 读四端点改 (oa:view || oa:apply), 仅 apply 者返回体过滤为自己的提交 (operator_filter); 撤销/编辑补 oa:approve 并保留"本人可撤/改自己申请"规则。

---

*原则: 本文档存于项目根目录随代码一起维护, 代码大改时同步更新。*
