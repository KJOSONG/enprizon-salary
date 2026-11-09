---
name: P17 移动端对齐重写完成
description: 2026-08-14 P17 移动端 4 页面重写完成并部署,QA 三轮验收全过,含用户 5 项新需求
type: project
---

## 2026-08-14 P17 移动端对齐重写(已上线,main=b8eb6f5)

### 完整交付链(main 分支 commit 从 3cbce3d → b8eb6f5)
1. `3cbce3d` hotfix: mobile.html 静态资源 `/static/...` → `static_url`(子路径 404 bug)
2. `97f6f7c` + `7161754`: mobile.css token 补齐 + 设计对齐规范文档
3. `aceac35`~`87a9a76`(5 commit): mobile.html 717→1124 行,4 页全重写
4. `3cd6be3`: i18n.js 挂载 `window.I18N_DICT`(移动端 t() 返回 key 的 bug)
5. `4584813`+`382875f`+`c7ae4c8`: dashboard_title + API_BASE + P1 视觉修复
6. `3aac1f8`+`1f39787`: 用户 5 项新需求(趋势排序/K线/筛选箭头/出勤排序/采集部门过滤)
7. `cf0d276`: 趋势图双击重置(zoom 精简版无 doubleClick,改手动 dblclick)
8. `a5d5a28`+`a51385f`+`c8b5aac`: 用户 5 项新需求(快捷操作迁移/请假类型/出勤工具栏/三个申请页/三道杠菜单)
9. `b8eb6f5`: 登录后刷新 STATE.auth(菜单用户名"—" bug,doLogin 改 checkAuth())

### 用户 5 项新需求(2026-08-14)
1. **趋势日期排序**:loadDashboard 对 shift/driller/crush_production 按 date 升序排序(ISO 字符串比较)
2. **筛选箭头倒字**:`.control-bar.open .ctrl-arrow { rotate(180deg) }` 作用在含文字 span → 文字分离 + SVG 箭头
3. **K 线式交互**:本地引入 chartjs-plugin-zoom v2.0.1(static/js/,无 CDN)+ 十字光标 crosshair + tooltip 三值(白/夜/合计)+ 双击重置(dblclick 监听 resetZoom + touch-action:manipulation)
4. **出勤员工 A-Z**:renderAttGrid 按 name localeCompare 排序(员工列表后端 ORDER BY name 一致)
5. **采集部门过滤 + 井下驾驶员联动**:`deptPool(kind)` 中文 contains 匹配;井下=含"井下"、钻工=含"钻工"、破碎=含"破碎"或"分拣"、出勤收集=不含前三者;井下驾驶员候选=已选出勤人员(refreshUgDrivers);payload 结构不变,后端零改动

### QA 四轮验收(mobile-p17 团队)
- R1: 55/55(PROXY 模式)+ 发现 P0(API 前缀)
- R2: 27/27(原生模式,P0 修复后登录成功)
- R3: 22/23(双击重置失败)→ smoke 4/4 通过
- R4: 21/22(菜单用户名"—" → b8eb6f5 修复,端到端验证通过)
- 最终状态:全部 P0+P1 修复,5 项大需求 + 5 项新需求全部上线

### 关键经验(踩坑)
- **API 也要加前缀**:mobile.html api() 曾直接 fetch(path),生产 /api/* 被 nginx 反代到 stock 系统(不是 salary)→ 登录 404。与静态资源同源问题,API_BASE 从 window.location.pathname 提取(对齐 index.html:1233-1239)
- **const 不挂 window**:`const I18N_DICT` 词法作用域,`window.I18N_DICT` 恒 undefined。需显式 `window.I18N_DICT = I18N_DICT`
- **dev 多次误在 main commit**:需 git cherry-pick 迁移 + main reset --hard origin/main,已 3 次发生。若 dev 再误提交,注意检查 main 是否被污染
- **chartjs-plugin-zoom 精简版无 doubleClick 配置**:12KB 版只支持 pan/wheel/drag/pinch,双击重置要手动 dblclick 监听

### 剩余(可选)
- 6 项 P2:登录按钮色(验收措辞)/部门脏数据/viewer 薪资概览权限/员工搜索栏初始隐藏/出勤部门 select 样式/筛选箭头(已修)
- 真机 pinch 手势需 iPhone 实测
- mobile-p17 团队保留(用户选择),designer/dev/qa context 可复用

### mobile-p17 团队状态
- 团队成员:designer(已 idle)、dev(已 idle)、qa(已 idle)
- 分支:feature/mobile-p17 已合并入 main(用户选择"合并 main + 部署"模式,非独立分支长期维护)
- 用户选择"保留团队不关闭"
