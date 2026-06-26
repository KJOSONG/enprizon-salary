/* ═══════════════════════════════════════════════════════
   Kilwa System — i18n 翻译引擎
   支持中文(zh) / English(en) 即时切换
   ═══════════════════════════════════════════════════════ */

const I18N_DICT = {
  zh: {
    /* ── 导航栏 ── */
    nav_dashboard: '数据台',
    nav_employees: '员工',
    nav_salary: '薪资',
    nav_attendance: '出勤',
    nav_dailywages: '日工资',
    nav_settings: '配置',
    btn_recalc: '重新计算',
    btn_recalc_loading: '计算中...',
    btn_reload: '↻',
    btn_export: '📥 导出报表',
    lang_zh: '中文',
    lang_en: 'EN',
    month_all: '全部月份',

    /* ── 数据台 ── */
    dash_overview: '数据概览',
    dash_connected: '已连接',
    dash_loading: '加载中',
    dash_total_emp: '总员工',
    dash_total_gross: '应发合计 (TZS)',
    dash_total_bonus: '奖金合计 (TZS)',
    dash_total_penalty: '罚款合计 (TZS)',
    dash_advance_deduct: '预支扣除 (TZS)',
    dash_nssf_deduct: 'NSSF扣除 (TZS)',
    dash_driver_allowance: '司机津贴 (TZS)', 
    dash_total_net: '实发合计 (TZS)',
    dash_ug_dr_dayrate: '井下 / 钻工 / 日薪',
    dash_prod_trend: '产量趋势 · NICKEL(H)(L) / MAWE',
    dash_prod_verify: '产量核验 ⚡',
    dash_driller_rank: '钻工产量排名',
    dash_consumables: '耗材统计',
    dash_category_pie: '品类占比',
    dash_show_labels: '显示标签',
    dash_labels: '标签',
    dash_reload: '重新加载',
    dash_recalc: '重新计算',
    dash_emp_mgmt: '员工管理',
    dash_salary_table: '薪资总表',
    dash_att_mgmt: '出勤管理',

    /* ── 员工管理 ── */
    emp_title: '员工管理',
    emp_all_types: '全部类型',
    emp_ug_piece: '井下计件',
    emp_dr_piece: '钻工计件',
    emp_dayrate: '日薪',
    emp_monthly: '月薪',
    emp_both: '需指定',
    emp_advance_only: '仅预支',
    emp_all_depts: '全部部门',
    th_name: '姓名',
    th_dept: '部门',
    th_current_type: '当前类型',
    th_dayrate_base: '日薪基数',
    th_monthly_base: '月薪基数',
    th_advance: '预支',
    th_bonus: '奖金',
    th_penalty: '罚款',
    th_nssf: 'NSSF',
    th_note: '备注',
    th_actions: '操作',
    ph_search: '搜索姓名...',

    /* ── 薪资 ── */
    salary_title: '全员工资表',
    salary_all_types: '全部类型',
    th_type: '类型',
    th_ug_piece: '井下计件',
    th_dr_piece: '钻工计件',
    th_dayrate: '日薪',
    th_monthly: '月薪',
    th_gross: '应发',
    th_net: '实发',
    th_temp_exception: '临时例外',
    salary_stats_emp: '员工',
    salary_stats_gross: '应发合计',
    salary_stats_bonus: '奖金合计',
    salary_stats_penalty: '罚款合计',
    salary_stats_advance: '预支扣除',
    salary_stats_nssf: 'NSSF扣除',
    salary_stats_driver: '司机津贴',
    salary_stats_net: '实发合计',

    /* ── 薪资核对 ── */
    salary_verify_title: '薪资双路径核对',
    salary_verify_pass: '✅ 核对一致',
    salary_verify_fail: '⚠️ 存在差异',
    salary_verify_expand: '▼ 展开明细',
    salary_verify_collapse: '▲ 收起明细',
    verify_ug_piece: '井下计件',
    verify_dr_piece: '钻工计件',
    verify_path1: '路径一（基准）',
    verify_path2: '路径二（实际）',
    verify_diff: '差值',
    verify_daily_compare: '逐日对比（路径一 vs 路径二，按日对齐）',
    verify_perfect: '✅ 完全一致',
    verify_day_diff: '天存在日级差异',
    verify_col_date: '日期',
    verify_col_path1: '路径一（产量×单价）',
    verify_col_path2: '路径二（员工日汇总）',
    verify_col_diff: '差异',
    verify_path1_title: '路径一 · 基准计算（产量 × 单价）',
    verify_no_data: '无对比数据',
    verify_rounding: '(舍入)',
    verify_ug_headers: '<tr><th>日期</th><th>NH</th><th>NL</th><th>MW</th><th>白班金额</th><th>夜班金额</th><th>合计</th></tr>',
    verify_dr_headers: '<tr><th>日期</th><th>队长</th><th>NH</th><th>NL</th><th>MW</th><th>金额</th></tr>',
    verify_no_data_row: '无数据',
    verify_captain_col: '队长',
    verify_driller_total: '钻工合计',
    verify_ug_total: '井下合计',
    verify_check: '核验',
    verify_all_match: '✅ 全部匹配',
    verify_mismatch: '❌ 存在不匹配，请检查',

    /* ── 日工资 ── */
    dw_title: '逐日工资明细',
    dw_all_types: '全部类型',
    dw_all_depts: '全部部门',
    dw_person: '人',
    dw_legend_dashed: '黄色虚线 = 手动变更（临时例外/出勤更改）',
    dw_legend_gray: '灰色数字 = 月薪默认',
    dw_total: '合计',
    dw_no_data: '无数据',
    dw_shift_col: '班次▼',
    dw_shift_all: '全',

    /* ── 出勤 ── */
    att_title: '出勤网格',
    att_all: '全部',
    att_search_ph: '搜索姓名...',
    att_reset: '↺ 复位',
    att_legend: 'D=白班 N=夜班 B=全天 P=出勤 A=旷工 L=请假 (P)=月薪默认 虚线下划线=手动更改 黄色虚线=月薪默认更改',
    shift_D_label: 'D',
    shift_N_label: 'N',
    shift_B_label: 'B',
    shift_P_label: 'P',
    shift_A_label: 'A',
    shift_L_label: 'L',
    shift_DP_label: '(P)',
    shift_D_desc: '白班',
    shift_N_desc: '夜班',
    shift_B_desc: '全天',
    shift_P_desc: '出勤',
    shift_A_desc: '旷工',
    shift_L_desc: '请假',
    shift_DP_desc: '月薪默认',

    /* ── 配置 ── */
    settings_title: '计算参数配置',
    settings_desc: '修改后自动重新计算',
    settings_ug_price: '井下计件单价',
    settings_dr_price: '钻工计件单价',
    settings_nssf_rate: 'NSSF 费率',
    settings_nssf_rate_pct: '费率(%)',
    settings_driver_allowance_title: '司机津贴',
    settings_driver_amount: '金额(TZS)',
    settings_driver_desc: '企业级司机运输津贴，手工输入后加入实发合计',
    settings_reset_default: '↺ 恢复默认',

    /* ── 审计日志 ── */
    audit_title: '审计日志',
    audit_refresh: '↻ 刷新',
    audit_th_time: '时间',
    audit_th_action: '操作',
    audit_th_employee: '员工',
    audit_th_detail: '详情',

    /* ── 模态框 ── */
    modal_title_override: '例外管理',
    modal_close: '关闭',
    modal_section1: '① 薪资类型设置',
    modal_section2: '② 临时例外 ⏳',
    modal_section3: '③ 已有临时例外',
    modal_temp_desc: '在指定日期区间内暂时切换薪资类型，仅当月有效，下月自动恢复。',
    modal_emp: '员工',
    modal_new_type: '新类型',
    modal_dayrate_base_label: '日薪基数(TZS)',
    modal_monthly_base_label: '月薪基数(TZS)',
    modal_piece_hint: '计件类型不需要设置基数',
    modal_save_type: '保存类型',
    modal_temp_type: '临时类型',
    modal_temp_dayrate: '日薪基数',
    modal_temp_shift: '班次',
    modal_temp_captain: '所属队长',
    modal_temp_start: '开始日期',
    modal_temp_end: '结束日期',
    modal_temp_note: '备注',
    modal_temp_note_ph: '如: 临时调去地面',
    modal_save_temp: '保存临时例外',
    modal_shift_day: '白班 (D)',
    modal_shift_night: '夜班 (N)',
    modal_select_captain: '选择队长',
    modal_no_temp: '无临时例外',
    modal_temp_loading: '加载中…',
    modal_temp_delete: '✕ 删除',

    /* ── 类型标签 ── */
    type_ug_piece: '井下计件',
    type_dr_piece: '钻工计件',
    type_dayrate: '日薪',
    type_monthly: '月薪',
    type_both: '需指定',
    type_advance_only: '仅预支',

    /* ── 来源文件 ── */
    source_no_file: '无源文件',
    source_please_add: '请放入 data/source/ 目录',
    source_main: '主产量表',
    source_advance: '预支表',
    source_addressbook: '通讯录',

    /* ── 源文件上传 ── */
    source_upload_title: '源文件管理',
    source_upload_desc: '上传 Excel 文件，自动覆盖旧文件并重新加载数据',
    source_upload_main: '主数据文件（考勤+计件）',
    source_upload_advance: '预支汇总文件',
    source_upload_addressbook: '通讯录文件',
    source_upload_nssf: 'NSSF 社保名单',
    source_upload_current: '当前文件',
    source_upload_none: '无文件',
    source_upload_select: '选择文件',
    source_upload_download: '下载模板',
    source_upload_success: '上传成功，数据已重新加载',
    source_upload_fail: '上传失败',
    source_upload_uploading: '上传中...',

    /* ── Toast ── */
    toast_calc_done: '计算完成',
    toast_load_fail: '加载失败: ',
    toast_month_switch: '切换月份...',
    toast_month_switched: '月份已切换',
    toast_month_fail: '切换失败',
    toast_reload_data: '重新加载数据...',
    toast_reload_done: '数据已重新加载',
    toast_reload_fail: '重新加载失败',
    toast_exporting: '正在生成完整报表...',
    toast_export_done: '报表导出成功',
    toast_admin_only: '此操作仅限管理员',
    toast_export_fail: '导出失败',
    toast_need_calc: '请先计算薪资',
    toast_saved: '配置已保存',
    toast_reset_done: '已恢复默认配置',
    toast_driver_updated: '司机津贴已更新',
    toast_temp_saved: '临时例外已保存，下月自动恢复',
    toast_type_set_pre: '已设为 ',
    toast_operation_fail: '操作失败',
    toast_login_success: '登录成功',
    toast_logout_success: '已退出登录',
    toast_admin_created: '管理员账号已创建',
    toast_delete_fail: '删除失败',
    toast_deleted: '已删除',
    toast_network_error: '操作失败: ',
    toast_select_month_first: '请先选择具体月份',

    /* ── 登录/改密 ── */
    btn_login: '登录',
    btn_change_pwd: '改密',
    btn_logout: '退出',
    btn_cancel: '取消',
    login_title: '管理员登录',
    login_setup_hint: '首次使用，请设置管理员账号',
    login_username: '用户名',
    login_password: '密码',
    chgpwd_title: '修改密码',
    chgpwd_old: '当前密码',
    chgpwd_new: '新密码',
    chgpwd_confirm: '确认新密码',
    chgpwd_submit: '确认修改',
    err_fill_all: '请填写所有字段',
    err_pwd_too_short: '新密码至少4位',
    err_pwd_mismatch: '两次输入的密码不一致',
    err_invalid_old_pwd: '当前密码错误',
    err_modify_failed: '修改失败',
    err_network: '网络错误',
    err_username_required: '请输入用户名和密码',
    err_invalid_credentials: '用户名或密码错误',
    login_success: '登录成功',
    logout_success: '已退出登录',
    admin_created: '管理员账号已创建',

    /* ── 奖金/罚款编辑 ── */
    bp_edit_title: '编辑奖金/罚款',

    /* ── 审计操作标签 ── */
    audit_override_save: '修改薪资类型',
    audit_attendance_toggle: '修改出勤',
    audit_attendance_reset: '复位出勤',
    audit_nssf_toggle: '切换NSSF',
    audit_recalculate: '重新计算',
    audit_reload_source: '重新加载',
    audit_config_update: '修改配置',
    audit_bonus_penalty_update: '修改奖金/罚款',

    /* ── 确认 ── */
    confirm_delete_override: '删除此例外？',
    confirm_delete_temp: '确定删除该条临时例外？',
    confirm_driver_allowance: '请输入司机津贴金额 (TZS):',
    confirm_invalid_number: '请输入有效的非负整数',

    /* ── 导出 ── */
    export_filename: 'ENPRIZON_LINDI_报表.xlsx',

    /* ── 产量核验表头 ── */
    verify_day_amt: '白班金额',
    verify_night_amt: '夜班金额',

    /* ── 图表数据集 ── */
    chart_nh: 'NH',
    chart_nl: 'NL', 
    chart_mw: 'MW',
    chart_futa: 'FUTA',
    chart_waya: 'WAYA',
    chart_kibiriti: 'KIBIRITI',

    /* ── 点击编辑 ── */
    dash_edit_driver_allowance: '点击编辑司机津贴',

    /* ── 离职员工 ── */
    emp_dismiss: '离职',
    emp_restore: '恢复',
    emp_dismiss_confirm: '确定要标记此员工为离职吗？标记后可从"已离职"列表中恢复。',
    emp_show_dismissed: '已离职',
    emp_hide_dismissed: '隐藏已离职',
    emp_dismissed_title: '已离职员工',
    emp_no_dismissed: '无已离职员工',

    /* ── Headless 预览模式 ── */
    headless_banner_dash: '📋 预览模式 — 当月暂无源数据，仅支持出勤记录与奖金/罚款',
    headless_banner_att: '📋 预览模式 — 当月暂无源数据，可手动记录出勤（P/A/L）。上传源数据后手动标记不会被覆盖。',

    /* ── 审计 ── */
    audit_dismiss_employee: '标记离职',
    audit_restore_employee: '恢复离职',
  },
  en: {
    /* ── Navigation ── */
    nav_dashboard: 'Dashboard',
    nav_employees: 'Employees',
    nav_salary: 'Salary',
    nav_attendance: 'Attendance',
    nav_dailywages: 'Daily Wages',
    nav_settings: 'Settings',
    btn_recalc: 'Recalculate',
    btn_recalc_loading: 'Calculating...',
    btn_reload: '↻',
    btn_export: '📥 Export Report',
    lang_zh: '中文',
    lang_en: 'EN',
    month_all: 'All Months',

    /* ── Dashboard ── */
    dash_overview: 'Overview',
    dash_connected: 'Connected',
    dash_loading: 'Loading',
    dash_total_emp: 'Total Employees',
    dash_total_gross: 'Gross Pay (TZS)',
    dash_total_bonus: 'Total Bonus (TZS)',
    dash_total_penalty: 'Total Penalty (TZS)',
    dash_advance_deduct: 'Advance Deduction (TZS)',
    dash_nssf_deduct: 'NSSF Deduction (TZS)',
    dash_driver_allowance: 'Driver Allowance (TZS)',
    dash_total_net: 'Net Pay (TZS)',
    dash_ug_dr_dayrate: 'Underground / Driller / Day Rate',
    dash_prod_trend: 'Production Trend · NICKEL(H)(L) / MAWE',
    dash_prod_verify: 'Production Verification ⚡',
    dash_driller_rank: 'Driller Production Ranking',
    dash_consumables: 'Consumables Statistics',
    dash_category_pie: 'Category Breakdown',
    dash_show_labels: 'Show Labels',
    dash_labels: 'Labels',
    dash_reload: 'Reload',
    dash_recalc: 'Recalculate',
    dash_emp_mgmt: 'Employee Mgmt',
    dash_salary_table: 'Salary Table',
    dash_att_mgmt: 'Attendance Mgmt',

    /* ── Employees ── */
    emp_title: 'Employee Management',
    emp_all_types: 'All Types',
    emp_ug_piece: 'Underground Piece',
    emp_dr_piece: 'Driller Piece',
    emp_dayrate: 'Day Rate',
    emp_monthly: 'Monthly',
    emp_both: 'Need Spec',
    emp_advance_only: 'Advance Only',
    emp_all_depts: 'All Departments',
    th_name: 'Name',
    th_dept: 'Department',
    th_current_type: 'Type',
    th_dayrate_base: 'Day Rate Base',
    th_monthly_base: 'Monthly Base',
    th_advance: 'Advance',
    th_bonus: 'Bonus',
    th_penalty: 'Penalty',
    th_nssf: 'NSSF',
    th_note: 'Note',
    th_actions: 'Actions',
    ph_search: 'Search name...',

    /* ── Salary ── */
    salary_title: 'Salary Table',
    salary_all_types: 'All Types',
    th_type: 'Type',
    th_ug_piece: 'Underground Piece',
    th_dr_piece: 'Driller Piece',
    th_dayrate: 'Day Rate',
    th_monthly: 'Monthly',
    th_gross: 'Gross',
    th_net: 'Net',
    th_temp_exception: 'Temp Exception',
    salary_stats_emp: 'Employees',
    salary_stats_gross: 'Gross Total',
    salary_stats_bonus: 'Total Bonus',
    salary_stats_penalty: 'Total Penalty',
    salary_stats_advance: 'Advance Deduction',
    salary_stats_nssf: 'NSSF Deduction',
    salary_stats_driver: 'Driver Allow.',
    salary_stats_net: 'Net Total',

    /* ── Salary Verification ── */
    salary_verify_title: 'Dual-Path Salary Verification',
    salary_verify_pass: '✅ Verified',
    salary_verify_fail: '⚠️ Discrepancy Found',
    salary_verify_expand: '▼ Expand Details',
    salary_verify_collapse: '▲ Collapse Details',
    verify_ug_piece: 'Underground Piece',
    verify_dr_piece: 'Driller Piece',
    verify_path1: 'Path 1 (Baseline)',
    verify_path2: 'Path 2 (Actual)',
    verify_diff: 'Difference',
    verify_daily_compare: 'Daily Comparison (Path 1 vs Path 2, Aligned by Date)',
    verify_perfect: '✅ Perfect Match',
    verify_day_diff: ' days with daily-level difference',
    verify_col_date: 'Date',
    verify_col_path1: 'Path 1 (Output × Price)',
    verify_col_path2: 'Path 2 (Employee Daily Sum)',
    verify_col_diff: 'Diff',
    verify_path1_title: 'Path 1 · Baseline (Output × Price)',
    verify_no_data: 'No comparison data',
    verify_rounding: '(rounding)',
    verify_ug_headers: '<tr><th>Date</th><th>NH</th><th>NL</th><th>MW</th><th>Day Amount</th><th>Night Amount</th><th>Total</th></tr>',
    verify_dr_headers: '<tr><th>Date</th><th>Captain</th><th>NH</th><th>NL</th><th>MW</th><th>Amount</th></tr>',
    verify_no_data_row: 'No Data',
    verify_captain_col: 'Captain',
    verify_driller_total: 'Driller Total',
    verify_ug_total: 'UG Total',
    verify_check: 'Verify',
    verify_all_match: '✅ All Match',
    verify_mismatch: '❌ Mismatch Found',

    /* ── Daily Wages ── */
    dw_title: 'Daily Wage Details',
    dw_all_types: 'All Types',
    dw_all_depts: 'All Departments',
    dw_person: 'persons',
    dw_legend_dashed: 'Yellow dashed = Manual change (temp override/attendance change)',
    dw_legend_gray: 'Gray numbers = Monthly default',
    dw_total: 'Total',
    dw_no_data: 'No Data',
    dw_shift_col: 'Shift▼',
    dw_shift_all: 'All',

    /* ── Attendance ── */
    att_title: 'Attendance Grid',
    att_all: 'All',
    att_search_ph: 'Search name...',
    att_reset: '↺ Reset',
    att_legend: 'D=Day N=Night B=Both P=Present A=Absent L=Leave (P)=Monthly Default Dashed underline=Manual change Yellow dashed=Monthly default change',
    shift_D_label: 'D',
    shift_N_label: 'N',
    shift_B_label: 'B',
    shift_P_label: 'P',
    shift_A_label: 'A',
    shift_L_label: 'L',
    shift_DP_label: '(P)',
    shift_D_desc: 'Day',
    shift_N_desc: 'Night',
    shift_B_desc: 'Both',
    shift_P_desc: 'Present',
    shift_A_desc: 'Absent',
    shift_L_desc: 'Leave',
    shift_DP_desc: 'Monthly Default',

    /* ── Settings ── */
    settings_title: 'Calculation Parameters',
    settings_desc: 'Auto-recalculate after changes',
    settings_ug_price: 'Underground Piece Rates',
    settings_dr_price: 'Driller Piece Rates',
    settings_nssf_rate: 'NSSF Rate',
    settings_nssf_rate_pct: 'Rate(%)',
    settings_driver_allowance_title: 'Driver Allowance',
    settings_driver_amount: 'Amount(TZS)',
    settings_driver_desc: 'Enterprise-level driver transport allowance, manually input and added to net pay total',
    settings_reset_default: '↺ Restore Defaults',

    /* ── Audit Log ── */
    audit_title: 'Audit Log',
    audit_refresh: '↻ Refresh',
    audit_th_time: 'Time',
    audit_th_action: 'Action',
    audit_th_employee: 'Employee',
    audit_th_detail: 'Details',

    /* ── Modal ── */
    modal_title_override: 'Override Management',
    modal_close: 'Close',
    modal_section1: '① Salary Type Setting',
    modal_section2: '② Temporary Exception ⏳',
    modal_section3: '③ Existing Temp Exceptions',
    modal_temp_desc: 'Temporarily switch salary type within the specified date range. Current month only, auto-restore next month.',
    modal_emp: 'Employee',
    modal_new_type: 'New Type',
    modal_dayrate_base_label: 'Day Rate (TZS)',
    modal_monthly_base_label: 'Monthly Salary (TZS)',
    modal_piece_hint: 'Piece-rate types do not need a base rate',
    modal_save_type: 'Save Type',
    modal_temp_type: 'Temp Type',
    modal_temp_dayrate: 'Day Rate',
    modal_temp_shift: 'Shift',
    modal_temp_captain: 'Captain',
    modal_temp_start: 'Start Date',
    modal_temp_end: 'End Date',
    modal_temp_note: 'Note',
    modal_temp_note_ph: 'e.g. Temp transferred to surface',
    modal_save_temp: 'Save Temp Exception',
    modal_shift_day: 'Day Shift (D)',
    modal_shift_night: 'Night Shift (N)',
    modal_select_captain: 'Select Captain',
    modal_no_temp: 'No temporary exceptions',
    modal_temp_loading: 'Loading...',
    modal_temp_delete: '✕ Delete',

    /* ── Type Labels ── */
    type_ug_piece: 'Underground Piece',
    type_dr_piece: 'Driller Piece',
    type_dayrate: 'Day Rate',
    type_monthly: 'Monthly',
    type_both: 'Need Spec',
    type_advance_only: 'Advance Only',

    /* ── Source Files ── */
    source_no_file: 'No source file',
    source_please_add: 'Please add to data/source/ directory',
    source_main: 'Production Table',
    source_advance: 'Advance Table',
    source_addressbook: 'Address Book',

    /* ── Source File Upload ── */
    source_upload_title: 'Source File Management',
    source_upload_desc: 'Upload Excel files to replace and reload automatically',
    source_upload_main: 'Main Data (Attendance + Piece Rate)',
    source_upload_advance: 'Advance Records',
    source_upload_addressbook: 'Address Book',
    source_upload_nssf: 'NSSF SDL List',
    source_upload_current: 'Current',
    source_upload_none: 'No file',
    source_upload_select: 'Select File',
    source_upload_download: 'Download Template',
    source_upload_success: 'Uploaded and data reloaded',
    source_upload_fail: 'Upload failed',
    source_upload_uploading: 'Uploading...',

    /* ── Toast ── */
    toast_calc_done: 'Calculation complete',
    toast_load_fail: 'Load failed: ',
    toast_month_switch: 'Switching month...',
    toast_month_switched: 'Month switched',
    toast_month_fail: 'Switch failed',
    toast_reload_data: 'Reloading data...',
    toast_reload_done: 'Data reloaded',
    toast_reload_fail: 'Reload failed',
    toast_exporting: 'Generating report...',
    toast_export_done: 'Report exported successfully',
    toast_admin_only: 'Admin only operation',
    toast_export_fail: 'Export failed',
    toast_need_calc: 'Please calculate salary first',
    toast_saved: 'Configuration saved',
    toast_reset_done: 'Defaults restored',
    toast_driver_updated: 'Driver allowance updated',
    toast_temp_saved: 'Temp exception saved, auto-restore next month',
    toast_type_set_pre: 'Set to ',
    toast_operation_fail: 'Operation failed',
    toast_login_success: 'Login successful',
    toast_logout_success: 'Logged out',
    toast_admin_created: 'Admin account created',
    toast_delete_fail: 'Delete failed',
    toast_deleted: 'Deleted',
    toast_network_error: 'Operation error: ',
    toast_select_month_first: 'Please select a specific month first',

    /* ── Login/Password ── */
    btn_login: 'Login',
    btn_change_pwd: 'Password',
    btn_logout: 'Logout',
    btn_cancel: 'Cancel',
    login_title: 'Admin Login',
    login_setup_hint: 'First time? Set up admin account',
    login_username: 'Username',
    login_password: 'Password',
    chgpwd_title: 'Change Password',
    chgpwd_old: 'Current Password',
    chgpwd_new: 'New Password',
    chgpwd_confirm: 'Confirm New Password',
    chgpwd_submit: 'Confirm',
    err_fill_all: 'Please fill in all fields',
    err_pwd_too_short: 'Password must be at least 4 characters',
    err_pwd_mismatch: 'Passwords do not match',
    err_invalid_old_pwd: 'Current password is incorrect',
    err_modify_failed: 'Failed to change password',
    err_network: 'Network error',
    err_username_required: 'Please enter username and password',
    err_invalid_credentials: 'Invalid username or password',
    login_success: 'Login successful',
    logout_success: 'Logged out',
    admin_created: 'Admin account created',

    /* ── Bonus/Penalty ── */
    bp_edit_title: 'Edit Bonus/Penalty',

    /* ── Audit Action Labels ── */
    audit_override_save: 'Change Salary Type',
    audit_attendance_toggle: 'Change Attendance',
    audit_attendance_reset: 'Reset Attendance',
    audit_nssf_toggle: 'Toggle NSSF',
    audit_recalculate: 'Recalculate',
    audit_reload_source: 'Reload Source',
    audit_config_update: 'Update Config',
    audit_bonus_penalty_update: 'Update Bonus/Penalty',

    /* ── Confirm ── */
    confirm_delete_override: 'Delete this override?',
    confirm_delete_temp: 'Delete this temporary exception?',
    confirm_driver_allowance: 'Enter driver allowance amount (TZS):',
    confirm_invalid_number: 'Please enter a valid non-negative integer',

    /* ── Export ── */
    export_filename: 'ENPRIZON_LINDI_Report.xlsx',

    /* ── Verification Table Headers ── */
    verify_day_amt: 'Day Amount',
    verify_night_amt: 'Night Amount',

    /* ── Chart Datasets ── */
    chart_nh: 'NH',
    chart_nl: 'NL',
    chart_mw: 'MW',
    chart_futa: 'FUTA',
    chart_waya: 'WAYA',
    chart_kibiriti: 'KIBIRITI',

    /* ── Other ── */
    dash_edit_driver_allowance: 'Click to edit driver allowance',

    /* ── Dismissed Employees ── */
    emp_dismiss: 'Dismiss',
    emp_restore: 'Restore',
    emp_dismiss_confirm: 'Mark this employee as dismissed? They can be restored from the "Dismissed" list.',
    emp_show_dismissed: 'Dismissed',
    emp_hide_dismissed: 'Hide Dismissed',
    emp_dismissed_title: 'Dismissed Employees',
    emp_no_dismissed: 'No dismissed employees',

    /* ── Headless Preview Mode ── */
    headless_banner_dash: '📋 Preview Mode — No source data this month, attendance and bonus/penalty only',
    headless_banner_att: '📋 Preview Mode — No source data this month, manual attendance (P/A/L) supported. Manual marks are safe after uploading source data.',

    /* ── Audit ── */
    audit_dismiss_employee: 'Dismiss Employee',
    audit_restore_employee: 'Restore Employee',
  }
};

/* ════════════════════════════════════════════════
   i18n 引擎
   ════════════════════════════════════════════════ */

function getLang() {
  return localStorage.getItem('kilwa_lang') || 'zh';
}

function setLang(lang) {
  localStorage.setItem('kilwa_lang', lang);
}

/* 翻译函数 */
function t(key) {
  const lang = getLang();
  const dict = I18N_DICT[lang] || I18N_DICT['zh'];
  return dict[key] !== undefined ? dict[key] : key;
}

/* 获取当前 TYPE_LABELS（动态翻译） */
function getTypeLabels() {
  return {
    piece_underground: '<span class="badge badge-green">' + t('type_ug_piece') + '</span>',
    piece_driller: '<span class="badge badge-purple">' + t('type_dr_piece') + '</span>',
    day_rate: '<span class="badge badge-blue">' + t('type_dayrate') + '</span>',
    monthly: '<span class="badge badge-yellow">' + t('type_monthly') + '</span>',
    both: '<span class="badge badge-red">' + t('type_both') + '</span>',
    advance_only: '<span class="badge badge-yellow">' + t('type_advance_only') + '</span>',
  };
}

/* 遍历 DOM 应用翻译 */
function applyI18n() {
  /* 1. data-i18n — 替换 element 文本 */
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.getAttribute('data-i18n');
    if (key) el.textContent = t(key);
  });

  /* 2. data-i18n-placeholder — 替换 placeholder */
  document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
    const key = el.getAttribute('data-i18n-placeholder');
    if (key) el.placeholder = t(key);
  });

  /* 3. data-i18n-title — 替换 title */
  document.querySelectorAll('[data-i18n-title]').forEach(el => {
    const key = el.getAttribute('data-i18n-title');
    if (key) el.title = t(key);
  });

  /* 4. data-i18n-html — 替换 innerHTML（用于包含 HTML 的翻译） */
  document.querySelectorAll('[data-i18n-html]').forEach(el => {
    const key = el.getAttribute('data-i18n-html');
    if (key) el.innerHTML = t(key);
  });

  /* 5. 更新语言切换按钮状态 */
  updateLangToggleUI();

  /* 6. 动态更新 TYPE_LABELS 引用（全局） */
  // TYPE_LABELS 在用到的地方通过 getTypeLabels() 获取，这里不强制刷新
}

/* 更新语言切换按钮 UI */
function updateLangToggleUI() {
  const lang = getLang();
  document.querySelectorAll('.lang-toggle-btn').forEach(btn => {
    const btnLang = btn.getAttribute('data-lang');
    btn.classList.toggle('active', btnLang === lang);
  });
}

/* 语言切换 */
function switchLang(lang) {
  if (!lang || !I18N_DICT[lang]) return;
  setLang(lang);
  applyI18n();

  /* ── 重渲染当前活跃页面 ── */
  const activePage = document.querySelector('.page.active');
  if (activePage) {
    const pageId = activePage.id;

    if (pageId === 'page-dashboard') {
      if (STATE.salaryResult) {
        renderDashboard(STATE.salaryResult);
        loadProductionData();
      }
    } else if (pageId === 'page-salary') {
      if (STATE._salaryResult) {
        renderSalaryTable(STATE._salaryResult);
      }
      if (STATE._verifyData) {
        renderSalaryVerification(STATE._verifyData);
      }
    } else if (pageId === 'page-employees') {
      renderEmployeeTable();
    } else if (pageId === 'page-dailywages') {
      renderDailyWages();
    } else if (pageId === 'page-attendance') {
      renderAttendance();
    } else if (pageId === 'page-settings') {
      loadConfig();
      loadAuditLog();
    }
  }

  /* 更新 recalc 按钮文字 */
  const recalcBtn = document.getElementById('recalcBtn');
  if (recalcBtn && !recalcBtn.disabled) {
    recalcBtn.textContent = t('btn_recalc');
  }

  /* 重新渲染产量核验表 */
  if (STATE._verifyData && typeof renderVerifyTable === 'function') {
    renderVerifyTable();
  }
}

/* ════════════════════════════════════════════════
   页面初始化时应用翻译
   ════════════════════════════════════════════════ */
document.addEventListener('DOMContentLoaded', function() {
  applyI18n();
});
