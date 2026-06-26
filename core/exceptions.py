"""
例外标记管理（持久化 — SQLite 版）
用户对员工薪资类型的覆盖、每日计件排除等信息保存在 SQLite 中
"""
from .database import load_overrides as _db_load, save_override as _db_save
from .database import remove_override as _db_remove, load_daily_exclusions as _db_excl

def load_overrides(data_folder):
    return _db_load(data_folder)

def save_override(data_folder, data):
    _db_save(data_folder, data)
    return True

def remove_override(data_folder, employee_id, index):
    _db_remove(data_folder, employee_id, index)
    return True

def load_daily_exclusions(data_folder):
    return _db_excl(data_folder)

def save_exclusion(data_folder, data):
    _db_save(data_folder, {**data, 'type': 'exclusion'})
    return True
