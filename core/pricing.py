"""
计算参数配置管理 — SQLite 版
"""
from .database import load_config as _db_load, save_config as _db_save

def load_config(data_folder):
    return _db_load(data_folder)

def save_config(data_folder, config):
    return _db_save(data_folder, config)
