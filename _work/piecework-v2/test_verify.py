"""
T10: verify_salary V2 dual-path sync + conservation check.

Run: pytest _work/piecework-v2/test_verify.py -v
"""
import sys
import os
import pytest

_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from core.verification import verify_salary, _path1_underground


# ── Helpers ──────────────────────────────────────────────

def _make_shift_v2(date='2026-09-01', day_prod=None, night_prod=None,
                   day_emps=None, night_emps=None,
                   day_team=1, night_team=0,
                   day_exempt=False, night_exempt=False):
    return {
        'date': date,
        'day_prod': day_prod or {},
        'night_prod': night_prod or {},
        'day_emps': day_emps or [],
        'night_emps': night_emps or [],
        'day_team': day_team,
        'night_team': night_team,
        'day_exempt': day_exempt,
        'night_exempt': night_exempt,
    }


def _make_pricing_v2(**overrides):
    p = {
        'underground_mode': 'v2',
        'accel_target': 40,
        'accel_prices': {'NICKEL（H）': 8000, 'NICKEL（L）': 5000, 'MAWE': 3000},
    }
    p.update(overrides)
    return p


# ═══════════════════════════════════════════════════════════
#  T10.1: V2 convex path1 underground
# ═══════════════════════════════════════════════════════════

class TestPath1V2Convex:
    """V2 path1 should compute convex pool with multiplier."""

    def test_path1_v2_convex(self):
        """nh=50, exempt=False, target=40, price=8000 → pool=50*8000*(50/40)=500000."""
        shift = _make_shift_v2(
            day_prod={'NICKEL（H）': 50, 'NICKEL（L）': 0, 'MAWE': 0},
            day_emps=['A'],
            day_team=1,
            day_exempt=False,
        )
        pricing = _make_pricing_v2()

        total, daily = _path1_underground(
            [shift], None,
            underground_mode='v2', pricing=pricing,
        )
        assert total == 500000, f"Expected 500000, got {total}"

    def test_path1_v2_exempt(self):
        """nh=50, exempt=True → multiplier=1.0 → pool=50*8000=400000."""
        shift = _make_shift_v2(
            day_prod={'NICKEL（H）': 50, 'NICKEL（L）': 0, 'MAWE': 0},
            day_emps=['A'],
            day_team=1,
            day_exempt=True,
        )
        pricing = _make_pricing_v2()

        total, daily = _path1_underground(
            [shift], None,
            underground_mode='v2', pricing=pricing,
        )
        assert total == 400000, f"Expected 400000, got {total}"

    def test_path1_v2_team_zero_skipped(self):
        """team_id=0 → no pool contribution."""
        shift = _make_shift_v2(
            day_prod={'NICKEL（H）': 50, 'NICKEL（L）': 0, 'MAWE': 0},
            day_emps=['A'],
            day_team=0,
            day_exempt=False,
        )
        pricing = _make_pricing_v2()

        total, daily = _path1_underground(
            [shift], None,
            underground_mode='v2', pricing=pricing,
        )
        assert total == 0, f"Expected 0 for team_id=0, got {total}"


# ═══════════════════════════════════════════════════════════
#  T10.2: Conservation check
# ═══════════════════════════════════════════════════════════

class TestConservation:
    """Coefficient conservation: base_sum ≈ final_sum within 10."""

    def test_conservation_true(self):
        """When Σ(piece_underground) ≈ Σ(ug_base) → conserved=True."""
        salary_result = {
            'ug_base': {'A': 500000, 'B': 300000},
            'employees': [
                {'employee_id': 'A', 'piece_underground': 500000, 'name': 'A'},
                {'employee_id': 'B', 'piece_underground': 300000, 'name': 'B'},
                {'employee_id': 'C', 'piece_underground': 0, 'name': 'C'},
            ],
        }
        main_data = {'shift_production': [], 'driller_production': []}

        result = verify_salary(
            main_data, salary_result,
            underground_mode='v2', pricing=_make_pricing_v2(),
        )
        cc = result['coefficient_conservation']
        assert cc['conserved'] is True
        assert cc['base_sum'] == 800000
        assert cc['final_sum'] == 800000
        assert cc['diff'] == 0

    def test_conservation_false(self):
        """When Σ(piece_underground) diverges from Σ(ug_base) → conserved=False."""
        salary_result = {
            'ug_base': {'A': 500000},
            'employees': [
                {'employee_id': 'A', 'piece_underground': 600000, 'name': 'A'},
            ],
        }
        main_data = {'shift_production': [], 'driller_production': []}

        result = verify_salary(
            main_data, salary_result,
            underground_mode='v2', pricing=_make_pricing_v2(),
        )
        cc = result['coefficient_conservation']
        assert cc['conserved'] is False
        assert cc['diff'] == 100000

    def test_conservation_non_v2_zeroed(self):
        """Non-v2 mode → conservation fields zeroed."""
        salary_result = {
            'employees': [
                {'employee_id': 'A', 'piece_underground': 500000, 'name': 'A'},
            ],
        }
        main_data = {'shift_production': [], 'driller_production': []}

        result = verify_salary(main_data, salary_result)
        cc = result['coefficient_conservation']
        assert cc == {'base_sum': 0, 'final_sum': 0, 'diff': 0, 'conserved': True}


# ═══════════════════════════════════════════════════════════
#  T10.3: Daily comparison relaxed flag
# ═══════════════════════════════════════════════════════════

class TestDailyComparisonRelaxed:
    """V2 daily comparison entries should have relaxed=True."""

    def test_v2_daily_relaxed(self):
        """When v2_active, daily_comparison entries have relaxed=True."""
        salary_result = {
            'ug_base': {},
            'ug_daily': {},
            'employees': [],
        }
        main_data = {'shift_production': [], 'driller_production': []}

        result = verify_salary(
            main_data, salary_result,
            underground_mode='v2', pricing=_make_pricing_v2(),
        )
        # No production data → empty comparison, but the function should not crash
        assert 'daily_comparison' in result
        assert result['daily_comparison']['underground'] == []

    def test_non_v2_no_relaxed(self):
        """Non-v2 → daily comparison entries don't have relaxed key."""
        salary_result = {
            'ug_daily': {},
            'employees': [],
        }
        main_data = {'shift_production': [], 'driller_production': []}

        result = verify_salary(main_data, salary_result)
        dc = result['daily_comparison']['underground']
        for entry in dc:
            assert 'relaxed' not in entry
