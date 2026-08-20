"""Tests for T3: V2 config keys (load_config defaults + save_config validation)."""
import os, sys, tempfile, shutil
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from core.database import load_config, save_config, init_db


def _make_folder():
    d = tempfile.mkdtemp()
    init_db(d)
    return d


def test_load_config_returns_v2_defaults():
    d = _make_folder()
    try:
        cfg = load_config(d)
        assert cfg['accel_target'] == 40
        assert cfg['accel_prices'] == {'NICKEL（H）': 8000, 'NICKEL（L）': 5000, 'MAWE': 3000}
        assert cfg['accel_w_a'] == 0.6
        assert cfg['accel_w_b'] == 0.4
        assert cfg['accel_full_days'] == 26
        assert cfg['v2_effective_from'] == ''
        assert cfg['underground_mode'] == 'piecework'
    finally:
        shutil.rmtree(d)


def test_load_config_setdefault_on_existing_rows():
    d = _make_folder()
    try:
        # save a minimal config without v2 keys
        save_config(d, {'underground_mode': 'piecework', 'crush_price': 300})
        cfg = load_config(d)
        assert cfg['accel_target'] == 40
        assert cfg['accel_w_a'] == 0.6
        assert cfg['underground_mode'] == 'piecework'
        assert cfg['crush_price'] == 300
    finally:
        shutil.rmtree(d)


def test_save_config_rejects_zero_accel_target():
    d = _make_folder()
    try:
        try:
            save_config(d, {'underground_mode': 'piecework', 'accel_target': 0})
            assert False, "should have raised ValueError"
        except ValueError:
            pass
    finally:
        shutil.rmtree(d)


def test_save_config_rejects_negative_accel_target():
    d = _make_folder()
    try:
        try:
            save_config(d, {'underground_mode': 'v2', 'accel_target': -5})
            assert False, "should have raised ValueError"
        except ValueError:
            pass
    finally:
        shutil.rmtree(d)


def test_save_config_rejects_wa_lte_wb():
    d = _make_folder()
    try:
        try:
            save_config(d, {'underground_mode': 'v2', 'accel_w_a': 0.3, 'accel_w_b': 0.6})
            assert False, "should have raised ValueError"
        except ValueError:
            pass
    finally:
        shutil.rmtree(d)


def test_save_config_rejects_wa_equals_wb():
    d = _make_folder()
    try:
        try:
            save_config(d, {'underground_mode': 'v2', 'accel_w_a': 0.5, 'accel_w_b': 0.5})
            assert False, "should have raised ValueError"
        except ValueError:
            pass
    finally:
        shutil.rmtree(d)


def test_save_config_rejects_bad_mode():
    d = _make_folder()
    try:
        try:
            save_config(d, {'underground_mode': 'invalid'})
            assert False, "should have raised ValueError"
        except ValueError:
            pass
    finally:
        shutil.rmtree(d)


def test_save_config_rejects_missing_accel_prices_keys():
    d = _make_folder()
    try:
        try:
            save_config(d, {'underground_mode': 'v2', 'accel_prices': {'NICKEL（H）': 8000}})
            assert False, "should have raised ValueError"
        except ValueError:
            pass
    finally:
        shutil.rmtree(d)


def test_save_config_accepts_valid():
    d = _make_folder()
    try:
        cfg = {
            'underground_mode': 'v2',
            'accel_target': 40,
            'accel_prices': {'NICKEL（H）': 8000, 'NICKEL（L）': 5000, 'MAWE': 3000},
            'accel_w_a': 0.6,
            'accel_w_b': 0.4,
        }
        assert save_config(d, cfg) is True
        loaded = load_config(d)
        assert loaded['accel_target'] == 40
    finally:
        shutil.rmtree(d)
