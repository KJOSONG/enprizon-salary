#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""组织重组验收：同代码对不同 DB 跑 2026-10 薪资管线，输出逐人逐项 JSON。

用法（服务器）：python3 verify_salary_identity.py /path/to/kilwa.db /tmp/out.json
在隔离目录挂载目标 DB（kilwa.db）+ 共享 uploads/，不动生产 data/。
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, '/root/enprizon-salary')

def main():
    db_src, out_json = sys.argv[1], sys.argv[2]
    tmp = tempfile.mkdtemp(prefix='orgverify_')
    shutil.copy(db_src, os.path.join(tmp, 'kilwa.db'))
    uploads = '/root/enprizon-salary/data/uploads'
    if os.path.isdir(uploads):
        os.symlink(uploads, os.path.join(tmp, 'uploads'))

    import app as appmod
    appmod.app.config['DATA_FOLDER'] = tmp
    md = appmod._run_pipeline('2026-10')
    if md is None:
        json.dump({'error': 'empty employees'}, open(out_json, 'w'))
        print('EMPTY'); return
    res = md['salary_result']
    emps = res.get('employees', [])
    dump = {}
    for e in emps:
        eid = str(e.get('employee_id') or e.get('id') or e.get('name'))
        dump[eid] = {k: e.get(k) for k in (
            'name', 'piece_underground', 'piece_driller', 'piece_crush',
            'day_rate', 'monthly', 'overtime', 'bonus', 'penalty',
            'driver_allowance', 'sick_subsidy', 'gross', 'paye', 'nssf',
            'net') if k in e}
    json.dump(dump, open(out_json, 'w'), ensure_ascii=False, default=str)
    total_gross = sum(v.get('gross', 0) or 0 for v in dump.values())
    total_net = sum(v.get('net', 0) or 0 for v in dump.values())
    print(f'employees={len(dump)} total_gross={total_gross} total_net={total_net}')
    shutil.rmtree(tmp, ignore_errors=True)

if __name__ == '__main__':
    main()
