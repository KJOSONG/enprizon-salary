"""出勤分部门横版报表 builder（纯 openpyxl，无 Flask 依赖）。

日期列来源 = GET /attendance 返回的 dates（整月自然日，monthrange 展开），
而非参考文件中的"截至最新数据日"（1..25）——网格一致性优先。
"""

import datetime as _dt

import openpyxl
from openpyxl.styles import Alignment, Border, Font, Side
from openpyxl.utils import get_column_letter


def sanitize_sheet_name(name, used):
    s = name or ""
    s = s.replace("/", "-")
    for ch in ":\\?*[]":
        s = s.replace(ch, "")
    s = s.strip()
    s = s[:31]
    if not s:
        s = "No Department"
    base = s
    candidate = base
    n = 2
    while candidate in used:
        suffix = f" -{n}"
        candidate = base[: 31 - len(suffix)] + suffix
        n += 1
    used.add(candidate)
    return candidate


def build_attendance_report(dates, rows):
    thin = Side(style="thin")
    border_thin = Border(left=thin, right=thin, top=thin, bottom=thin)
    font_bold = Font(bold=True)
    align_center = Alignment(horizontal="center")

    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    # group rows by department preserving input order within each dept
    groups: dict[str, list] = {}
    order: dict[str, int] = {}
    for r in rows:
        dept = r.get("department", "")
        if dept not in groups:
            groups[dept] = []
            order[dept] = len(order)
        groups[dept].append(r)

    # process depts in sorted() order of RAW department string
    sorted_depts = sorted(groups.keys())

    used_names: set[str] = set()

    for dept in sorted_depts:
        dept_rows = groups[dept]
        title = sanitize_sheet_name(dept, used_names)
        ws = wb.create_sheet(title)

        # header row
        ws["A1"] = "Name"
        ws["B1"] = "Department"
        for i, ds in enumerate(dates):
            col = 3 + i
            cell = ws.cell(row=1, column=col)
            cell.value = _dt.datetime(int(ds[0:4]), int(ds[5:7]), int(ds[8:10]))
            cell.number_format = "d"

        # style header row
        max_col = 2 + len(dates)
        for col in range(1, max_col + 1):
            cell = ws.cell(row=1, column=col)
            cell.font = font_bold
            cell.alignment = align_center
            cell.border = border_thin

        # data rows
        for r_idx, r in enumerate(dept_rows):
            row_num = 2 + r_idx
            c_a = ws.cell(row=row_num, column=1, value=r.get("name", ""))
            c_a.border = border_thin
            c_b = ws.cell(row=row_num, column=2, value=r.get("department", ""))
            c_b.border = border_thin
            days = r.get("days", {})
            for i, ds in enumerate(dates):
                col = 3 + i
                val = str(days.get(ds, ""))
                cell = ws.cell(row=row_num, column=col, value=val)
                cell.font = font_bold
                cell.alignment = align_center
                cell.border = border_thin

        # column widths
        if dept_rows:
            max_name_len = max(len(str(rr.get("name", ""))) for rr in dept_rows)
        else:
            max_name_len = 0
        w_a = max(max_name_len + 2, 22)
        if w_a > 30:
            w_a = 30
        ws.column_dimensions["A"].width = w_a

        if dept_rows:
            max_dept_len = max(len(str(rr.get("department", ""))) for rr in dept_rows)
        else:
            max_dept_len = len(title)
        w_b = max(max_dept_len + 2, 12)
        if w_b > 32:
            w_b = 32
        ws.column_dimensions["B"].width = w_b

        for i in range(len(dates)):
            col_letter = get_column_letter(3 + i)
            ws.column_dimensions[col_letter].width = 4

        ws.freeze_panes = "C2"
        ws.page_setup.orientation = "landscape"
        ws.page_setup.paperSize = 9
        ws.page_setup.fitToHeight = 0

    return wb
