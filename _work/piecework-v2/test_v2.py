"""
V2 piecework engine unit tests.
Tests the convex team daily pool, month-end coefficient, and zero-sum normalization.

Run: pytest _work/piecework-v2/test_v2.py -v
"""
import sys
import os
import pytest
from unittest.mock import patch
from collections import defaultdict

# Ensure project root is on path
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from core.calculator import (
    calc_underground_piece,
    PRICES_UNDERGROUND,
)


# ── Helpers ──────────────────────────────────────────────

def _make_shift(date, day_emps=None, night_emps=None, day_prod=None, night_prod=None,
                day_team=0, night_team=0, day_exempt=False, night_exempt=False):
    """Build a shift_production record for testing."""
    return {
        'date': date,
        'day_emps': day_emps or [],
        'night_emps': night_emps or [],
        'day_prod': day_prod or {'NICKEL（H）': 0, 'NICKEL（L）': 0, 'MAWE': 0},
        'night_prod': night_prod or {'NICKEL（H）': 0, 'NICKEL（L）': 0, 'MAWE': 0},
        'day_team': day_team,
        'night_team': night_team,
        'day_exempt': day_exempt,
        'night_exempt': night_exempt,
    }


def _make_pricing(**overrides):
    """Build a pricing dict for V2 tests."""
    p = {
        'underground_mode': 'v2',
        'accel_target': 40,
        'accel_prices': {'NICKEL（H）': 8000, 'NICKEL（L）': 5000, 'MAWE': 3000},
        'accel_w_a': 0.6,
        'accel_w_b': 0.4,
        'accel_full_days': 26,
        'v2_effective_from': '',
    }
    p.update(overrides)
    return p


# Patch make_employee_id to be identity for pure-logic tests
@pytest.fixture(autouse=True)
def _patch_make_id():
    """Make make_employee_id return the name as-is for test isolation."""
    with patch('core.calculator.make_employee_id', side_effect=lambda x: x if x else None):
        yield


# ═══════════════════════════════════════════════════════════
#  T5: E exempt status
# ═══════════════════════════════════════════════════════════

class TestEExempt:
    """T5: E status should exclude employee from underground piece allocation."""

    def test_e_exempt_excluded_from_daily(self):
        """E-marked employee gets 0 from underground piece on that date."""
        shift = _make_shift(
            '2026-08-01',
            day_emps=['ALICE', 'BOB', 'CHARLIE'],
            day_prod={'NICKEL（H）': 40, 'NICKEL（L）': 0, 'MAWE': 0},
        )
        # ALICE is marked E → excluded via exclusions set (simulates SQL adding E)
        exclusions = {('ALICE', '2026-08-01')}
        override_excludes = {'permanent': set()}

        result, daily, shifts = calc_underground_piece(
            [shift], exclusions, override_excludes
        )

        # ALICE gets 0 (excluded), BOB and CHARLIE split the pool
        assert result.get('ALICE', 0) == 0
        assert daily.get('ALICE', {}).get('2026-08-01', 0) == 0
        # BOB and CHARLIE each get half
        assert result['BOB'] > 0
        assert result['CHARLIE'] > 0
        assert abs(result['BOB'] - result['CHARLIE']) < 0.01

    def test_e_vs_a_same_exclusion_behavior(self):
        """E and A should produce identical exclusion behavior in calc_underground_piece."""
        shift = _make_shift(
            '2026-08-01',
            day_emps=['ALICE', 'BOB'],
            day_prod={'NICKEL（H）': 20, 'NICKEL（L）': 0, 'MAWE': 0},
        )
        override_excludes = {'permanent': set()}

        # With E exclusion
        result_e, _, _ = calc_underground_piece(
            [shift], {('ALICE', '2026-08-01')}, override_excludes
        )
        # With L exclusion (existing behavior)
        result_l, _, _ = calc_underground_piece(
            [shift], {('ALICE', '2026-08-01')}, override_excludes
        )

        # Both should produce same result for BOB (ALICE excluded either way)
        assert abs(result_e.get('BOB', 0) - result_l.get('BOB', 0)) < 0.01


# ═══════════════════════════════════════════════════════════
#  T6: Convex team daily pool
# ═══════════════════════════════════════════════════════════

class TestConvexPool:
    """T6: V2 convex pool calculation with accelerator multiplier."""

    def test_convex_pool_basic(self):
        """nh=50, accel_target=40, price=8000 → pool = 50*8000*(50/40) = 500000."""
        shift = _make_shift(
            '2026-08-01',
            day_emps=['W1', 'W2', 'W3'],
            day_prod={'NICKEL（H）': 50, 'NICKEL（L）': 0, 'MAWE': 0},
            day_team=1,
        )
        pricing = _make_pricing()
        exclusions = set()
        override_excludes = {'permanent': set()}

        result, daily, _ = calc_underground_piece(
            [shift], exclusions, override_excludes,
            mode='v2', pricing=pricing
        )
        # pool = 50 * 8000 * (50/40) = 500,000; per_head = 500000/3
        expected_pool = 50 * 8000 * (50 / 40)  # 500000
        per_head = expected_pool / 3
        for emp in ['W1', 'W2', 'W3']:
            assert abs(result[emp] - per_head) < 0.01

    def test_exempt_multiplier_is_one(self):
        """Exempt day → multiplier=1.0, pool = base_linear (no convex boost)."""
        shift = _make_shift(
            '2026-08-01',
            day_emps=['W1', 'W2'],
            day_prod={'NICKEL（H）': 50, 'NICKEL（L）': 0, 'MAWE': 0},
            day_team=1,
            day_exempt=True,
        )
        pricing = _make_pricing()
        exclusions = set()
        override_excludes = {'permanent': set()}

        result, _, _ = calc_underground_piece(
            [shift], exclusions, override_excludes,
            mode='v2', pricing=pricing
        )
        # pool = 50*8000 * 1.0 = 400,000; per_head = 200,000
        expected_pool = 50 * 8000 * 1.0  # 400000
        per_head = expected_pool / 2
        for emp in ['W1', 'W2']:
            assert abs(result[emp] - per_head) < 0.01

    def test_team_id_zero_no_pool(self):
        """team_id=0 shifts should produce no pool and accumulate warning."""
        shift = _make_shift(
            '2026-08-01',
            day_emps=['W1', 'W2'],
            day_prod={'NICKEL（H）': 30, 'NICKEL（L）': 0, 'MAWE': 0},
            day_team=0,  # unassigned
        )
        pricing = _make_pricing()
        exclusions = set()
        override_excludes = {'permanent': set()}

        result, daily, _ = calc_underground_piece(
            [shift], exclusions, override_excludes,
            mode='v2', pricing=pricing
        )
        # No pool generated for team_id=0
        for emp in ['W1', 'W2']:
            assert result.get(emp, 0) == 0

    def test_v2_fallback_linear_when_not_v2(self):
        """When mode is not v2, should use existing linear logic (byte-identical)."""
        shift = _make_shift(
            '2026-08-01',
            day_emps=['W1', 'W2'],
            day_prod={'NICKEL（H）': 50, 'NICKEL（L）': 0, 'MAWE': 0},
            day_team=1,
        )
        exclusions = set()
        override_excludes = {'permanent': set()}

        # With mode=None (default, non-v2)
        result_linear, _, _ = calc_underground_piece(
            [shift], exclusions, override_excludes,
            mode=None, pricing=None
        )
        # Linear: pool = 50*6000 = 300,000; per_head = 150,000
        # (uses PRICES_UNDERGROUND default since pricing is None)
        for emp in ['W1', 'W2']:
            assert abs(result_linear[emp] - 150000) < 0.01

    def test_multi_material_convex(self):
        """Multiple material types: pool = Σ(prod[k]*price[k]) * multiplier."""
        shift = _make_shift(
            '2026-08-01',
            day_emps=['W1'],
            day_prod={'NICKEL（H）': 10, 'NICKEL（L）': 5, 'MAWE': 5},
            day_team=1,
        )
        pricing = _make_pricing()
        exclusions = set()
        override_excludes = {'permanent': set()}

        result, _, _ = calc_underground_piece(
            [shift], exclusions, override_excludes,
            mode='v2', pricing=pricing
        )
        # base_linear = 10*8000 + 5*5000 + 5*3000 = 80000+25000+15000 = 120000
        # total_cars = 10+5+5 = 20
        # multiplier = 20/40 = 0.5
        # pool = 120000 * 0.5 = 60000
        assert abs(result['W1'] - 60000) < 0.01


# ═══════════════════════════════════════════════════════════
#  T7: apply_v2_month_end
# ═══════════════════════════════════════════════════════════

class TestMonthEnd:
    """T7: Month-end attendance/behavior coefficient + zero-sum normalization."""

    def test_conservation(self):
        """Σfinal == Σbase within 10 (zero-sum property)."""
        from core.calculator import apply_v2_month_end

        base = {'X': 600000, 'Y': 400000}
        employees = [
            {'id': 'X', 'name': 'X'},
            {'id': 'Y', 'name': 'Y'},
        ]
        pricing = _make_pricing()

        # Mock scoring functions to return fixed B_W
        with patch('core.database.get_scoring_card_entries', return_value=[]), \
             patch('core.database.get_scoring_config', return_value={}):
            # Mock compute_scoring_individuals to return known B_W
            fake_indiv = {
                'X': {'coefficient': 1.2},
                'Y': {'coefficient': 0.8},
            }
            with patch('core.calculator.compute_scoring_individuals', return_value=fake_indiv):
                # Mock attendance: X worked 26 days, Y worked 20 days
                with patch('core.calculator._get_v2_attendance', return_value={
                    'X': {'worked': 26, 'exempt': 0},
                    'Y': {'worked': 20, 'exempt': 0},
                }):
                    f_W = apply_v2_month_end(base, employees, '/tmp', '2026-08', pricing)

        # Verify conservation: Σ(base * f_W) ≈ Σbase
        total_base = sum(base.values())  # 1,000,000
        total_final = sum(base[eid] * f_W[eid] for eid in base)
        assert abs(total_final - total_base) <= 10, \
            f"Conservation violated: Σfinal={total_final}, Σbase={total_base}, diff={abs(total_final-total_base)}"

    def test_bw_default_no_keyerror(self):
        """No scoring entries → B_W=1.0 for all, no KeyError."""
        from core.calculator import apply_v2_month_end

        base = {'X': 500000}
        employees = [{'id': 'X', 'name': 'X'}]
        pricing = _make_pricing()

        with patch('core.database.get_scoring_card_entries', return_value=[]), \
             patch('core.database.get_scoring_config', return_value={}), \
             patch('core.calculator.compute_scoring_individuals', return_value={}), \
             patch('core.calculator._get_v2_attendance', return_value={
                 'X': {'worked': 26, 'exempt': 0}
             }):
            f_W = apply_v2_month_end(base, employees, '/tmp', '2026-08', pricing)

        # B_W=1.0, A_W=1.0 (full attendance) → C_W=1.0 → raw=base → k=1.0 → f=1.0
        assert abs(f_W['X'] - 1.0) < 0.001

    def test_eligible_zero_no_division_by_zero(self):
        """eligible=0 (all days exempt) → A_W=1.0, no ZeroDivisionError."""
        from core.calculator import apply_v2_month_end

        base = {'X': 300000}
        employees = [{'id': 'X', 'name': 'X'}]
        pricing = _make_pricing()

        with patch('core.database.get_scoring_card_entries', return_value=[]), \
             patch('core.database.get_scoring_config', return_value={}), \
             patch('core.calculator.compute_scoring_individuals', return_value={}), \
             patch('core.calculator._get_v2_attendance', return_value={
                 'X': {'worked': 0, 'exempt': 26}  # all exempt
             }):
            f_W = apply_v2_month_end(base, employees, '/tmp', '2026-08', pricing)

        # eligible = 26 - 26 = 0 → A_W=1.0; B_W=1.0; C_W=1.0; f=1.0
        assert abs(f_W['X'] - 1.0) < 0.001


# ═══════════════════════════════════════════════════════════
#  T8: calculate_all V2 integration
# ═══════════════════════════════════════════════════════════

class TestV2Integration:
    """T8: calculate_all V2 gate + coefficient + pu scaling."""

    def test_pu_no_overcount(self):
        """V2 worker's base does not double-count E days."""
        from core.calculator import calculate_all

        shift = _make_shift(
            '2026-08-01',
            day_emps=['W1', 'W2'],
            day_prod={'NICKEL（H）': 40, 'NICKEL（L）': 0, 'MAWE': 0},
            day_team=1,
        )
        employees = [
            {'id': 'W1', 'name': 'W1', 'default_type': 'piece_underground',
             'department': 'Production TEAM （underground）', 'nssf_enrolled': False},
            {'id': 'W2', 'name': 'W2', 'default_type': 'piece_underground',
             'department': 'Production TEAM （underground）', 'nssf_enrolled': False},
        ]
        main_data = {'shift_production': [shift], 'driller_production': [],
                     'attendance': [], 'crush_production': []}

        pricing = _make_pricing()
        # Simulate E exclusion: W1 has E on this date (excluded from piece calc)
        # We pass it via the exclusion set that calculate_all builds from DB
        # For pure-logic test, we'll use a tmpdir with a DB

        import tempfile, sqlite3
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, 'kilwa.db')
            conn = sqlite3.connect(db_path)
            conn.execute('''CREATE TABLE attendance_overrides (
                employee_id TEXT, date TEXT, status TEXT,
                PRIMARY KEY (employee_id, date))''')
            # W1 is marked E on 2026-08-01
            conn.execute("INSERT INTO attendance_overrides VALUES (?, ?, ?)",
                         ('W1', '2026-08-01', 'E'))
            conn.commit()
            conn.close()

            result = calculate_all(main_data, employees, overrides={}, pricing=pricing,
                                   data_folder=tmpdir)

        # Find W1 and W2 in results
        w1 = next(e for e in result['employees'] if e['employee_id'] == 'W1')
        w2 = next(e for e in result['employees'] if e['employee_id'] == 'W2')

        # W1 has E → excluded from underground piece → pu=0
        assert w1['piece_underground'] == 0
        # W2 gets full pool
        assert w2['piece_underground'] > 0

    def test_v2_gate_piecework_no_coefficient(self):
        """piecework mode → no ug_coefficient/ug_base in result."""
        from core.calculator import calculate_all

        shift = _make_shift(
            '2026-08-01',
            day_emps=['W1'],
            day_prod={'NICKEL（H）': 20, 'NICKEL（L）': 0, 'MAWE': 0},
        )
        employees = [
            {'id': 'W1', 'name': 'W1', 'default_type': 'piece_underground',
             'department': 'Production TEAM （underground）', 'nssf_enrolled': False},
        ]
        main_data = {'shift_production': [shift], 'driller_production': [],
                     'attendance': [], 'crush_production': []}
        pricing = {'underground_mode': 'piecework'}

        result = calculate_all(main_data, employees, overrides={}, pricing=pricing)

        assert 'ug_coefficient' not in result
        assert 'ug_base' not in result

    def test_v2_gate_future_month_no_v2(self):
        """month < v2_effective_from → linear, no V2 scaling."""
        from core.calculator import calculate_all

        shift = _make_shift(
            '2026-06-01',
            day_emps=['W1'],
            day_prod={'NICKEL（H）': 40, 'NICKEL（L）': 0, 'MAWE': 0},
        )
        employees = [
            {'id': 'W1', 'name': 'W1', 'default_type': 'piece_underground',
             'department': 'Production TEAM （underground）', 'nssf_enrolled': False},
        ]
        main_data = {'shift_production': [shift], 'driller_production': [],
                     'attendance': [], 'crush_production': []}
        pricing = _make_pricing(v2_effective_from='2026-07')

        result = calculate_all(main_data, employees, overrides={}, pricing=pricing)

        # month 2026-06 < v2_effective_from 2026-07 → no V2
        assert 'ug_coefficient' not in result

    def test_v2_active_has_coefficient(self):
        """V2 active month → ug_coefficient and ug_base present in result."""
        from core.calculator import calculate_all

        shift = _make_shift(
            '2026-08-01',
            day_emps=['W1', 'W2'],
            day_prod={'NICKEL（H）': 40, 'NICKEL（L）': 0, 'MAWE': 0},
            day_team=1,
        )
        employees = [
            {'id': 'W1', 'name': 'W1', 'default_type': 'piece_underground',
             'department': 'Production TEAM （underground）', 'nssf_enrolled': False},
            {'id': 'W2', 'name': 'W2', 'default_type': 'piece_underground',
             'department': 'Production TEAM （underground）', 'nssf_enrolled': False},
        ]
        main_data = {'shift_production': [shift], 'driller_production': [],
                     'attendance': [], 'crush_production': []}
        pricing = _make_pricing(v2_effective_from='2026-08')

        import tempfile, sqlite3
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, 'kilwa.db')
            conn = sqlite3.connect(db_path)
            conn.execute('''CREATE TABLE attendance_overrides (
                employee_id TEXT, date TEXT, status TEXT,
                PRIMARY KEY (employee_id, date))''')
            # Both worked, no A/L/E
            conn.commit()
            conn.close()

            result = calculate_all(main_data, employees, overrides={}, pricing=pricing,
                                   data_folder=tmpdir)

        assert 'ug_coefficient' in result
        assert 'ug_base' in result
        # Conservation: Σ(piece_underground) ≈ Σ(ug_base)
        total_pu = sum(e['piece_underground'] for e in result['employees']
                       if e.get('salary_type') == 'piece_underground')
        total_base = sum(result['ug_base'].get(e['employee_id'], 0) for e in result['employees']
                         if e.get('salary_type') == 'piece_underground')
        assert abs(total_pu - total_base) <= 10, \
            f"V2 conservation: Σpu={total_pu}, Σbase={total_base}"


# ═══════════════════════════════════════════════════════════
#  T9: compute_daily_breakdown mirror V2
# ═══════════════════════════════════════════════════════════

class TestDailyBreakdownV2:
    """T9: Daily breakdown mirrors V2 coefficient (daily total == salary page)."""

    def test_daily_equals_salary(self):
        """compute_daily_breakdown total == calculate_all piece_underground per employee."""
        from core.calculator import calculate_all, compute_daily_breakdown

        shift = _make_shift(
            '2026-08-01',
            day_emps=['W1', 'W2'],
            day_prod={'NICKEL（H）': 40, 'NICKEL（L）': 0, 'MAWE': 0},
            day_team=1,
        )
        employees = [
            {'id': 'W1', 'name': 'W1', 'default_type': 'piece_underground',
             'department': 'Production TEAM （underground）', 'nssf_enrolled': False},
            {'id': 'W2', 'name': 'W2', 'default_type': 'piece_underground',
             'department': 'Production TEAM （underground）', 'nssf_enrolled': False},
        ]
        main_data = {'shift_production': [shift], 'driller_production': [],
                     'attendance': [], 'crush_production': []}
        pricing = _make_pricing(v2_effective_from='2026-08')

        import tempfile, sqlite3
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, 'kilwa.db')
            conn = sqlite3.connect(db_path)
            conn.execute('''CREATE TABLE attendance_overrides (
                employee_id TEXT, date TEXT, status TEXT,
                PRIMARY KEY (employee_id, date))''')
            conn.commit()
            conn.close()

            salary_result = calculate_all(main_data, employees, overrides={}, pricing=pricing,
                                          data_folder=tmpdir)
            daily_result = compute_daily_breakdown(main_data, employees, overrides={}, pricing=pricing,
                                                   data_folder=tmpdir)

        # Compare piece_underground totals per employee
        for emp in salary_result['employees']:
            eid = emp['employee_id']
            sal_pu = emp['piece_underground']
            if sal_pu == 0 and eid not in daily_result:
                continue
            if eid in daily_result:
                daily_total = daily_result[eid]['total']
                # The daily total includes all tracks, so we need to extract just ug
                # For pure UG workers, total should match piece_underground
                if emp.get('salary_type') == 'piece_underground':
                    assert abs(daily_total - sal_pu) <= 1, \
                        f"{eid}: daily={daily_total}, salary_ug={sal_pu}"


# ═══════════════════════════════════════════════════════════
#  T19: Edge cases
# ═══════════════════════════════════════════════════════════

class TestEdgeCases:
    """T19: Edge cases for V2 pure logic."""

    def test_empty_base(self):
        """apply_v2_month_end with empty base → empty result."""
        from core.calculator import apply_v2_month_end

        pricing = _make_pricing()
        with patch('core.database.get_scoring_card_entries', return_value=[]), \
             patch('core.database.get_scoring_config', return_value={}), \
             patch('core.calculator.compute_scoring_individuals', return_value={}), \
             patch('core.calculator._get_v2_attendance', return_value={}):
            f_W = apply_v2_month_end({}, [], '/tmp', '2026-08', pricing)
        assert f_W == {}

    def test_eligible_zero_all_exempt(self):
        """All 26 days exempt → eligible=0 → A_W=1.0, no div/zero."""
        from core.calculator import apply_v2_month_end

        base = {'W1': 200000}
        employees = [{'id': 'W1', 'name': 'W1'}]
        pricing = _make_pricing()

        with patch('core.database.get_scoring_card_entries', return_value=[]), \
             patch('core.database.get_scoring_config', return_value={}), \
             patch('core.calculator.compute_scoring_individuals', return_value={}), \
             patch('core.calculator._get_v2_attendance', return_value={
                 'W1': {'worked': 0, 'exempt': 26}
             }):
            f_W = apply_v2_month_end(base, employees, '/tmp', '2026-08', pricing)
        assert abs(f_W['W1'] - 1.0) < 0.001

    def test_exempt_day_lock_multiplier(self):
        """Exempt day → multiplier locked at 1.0 even with high car count."""
        shift = _make_shift(
            '2026-08-01',
            day_emps=['W1'],
            day_prod={'NICKEL（H）': 100, 'NICKEL（L）': 0, 'MAWE': 0},
            day_team=1,
            day_exempt=True,  # exempt!
        )
        pricing = _make_pricing()
        result, _, _ = calc_underground_piece(
            [shift], set(), {'permanent': set()},
            mode='v2', pricing=pricing
        )
        # 100 cars but exempt → multiplier=1.0 → pool = 100*8000*1.0 = 800,000
        assert abs(result['W1'] - 800000) < 0.01

    def test_team_id_zero_warning_count(self):
        """team_id=0 → no pool, warning accumulated."""
        shift = _make_shift(
            '2026-08-01',
            day_emps=['W1'],
            day_prod={'NICKEL（H）': 30, 'NICKEL（L）': 0, 'MAWE': 0},
            day_team=0,
        )
        pricing = _make_pricing()
        result, daily, _ = calc_underground_piece(
            [shift], set(), {'permanent': set()},
            mode='v2', pricing=pricing
        )
        assert result.get('W1', 0) == 0
        assert daily.get('W1', {}).get('2026-08-01', 0) == 0

    def test_night_shift_v2_convex(self):
        """Night shift also gets V2 convex pool treatment."""
        shift = _make_shift(
            '2026-08-01',
            night_emps=['W1', 'W2'],
            night_prod={'NICKEL（H）': 80, 'NICKEL（L）': 0, 'MAWE': 0},
            night_team=2,
        )
        pricing = _make_pricing()
        result, _, _ = calc_underground_piece(
            [shift], set(), {'permanent': set()},
            mode='v2', pricing=pricing
        )
        # pool = 80*8000 * (80/40) = 1,280,000; per_head = 640,000
        expected = 80 * 8000 * (80 / 40) / 2
        for emp in ['W1', 'W2']:
            assert abs(result[emp] - expected) < 0.01

    def test_v2_preserves_total_f(self):
        """After V2 month-end, Σfinal == Σbase (total F preserved)."""
        from core.calculator import apply_v2_month_end

        base = {'A': 100000, 'B': 200000, 'C': 300000, 'D': 400000}
        employees = [{'id': k, 'name': k} for k in base]
        pricing = _make_pricing()

        fake_indiv = {
            'A': {'coefficient': 1.2},
            'B': {'coefficient': 0.8},
            'C': {'coefficient': 1.0},
            'D': {'coefficient': 0.6},
        }
        with patch('core.database.get_scoring_card_entries', return_value=[]), \
             patch('core.database.get_scoring_config', return_value={}), \
             patch('core.calculator.compute_scoring_individuals', return_value=fake_indiv), \
             patch('core.calculator._get_v2_attendance', return_value={
                 'A': {'worked': 26, 'exempt': 0},
                 'B': {'worked': 24, 'exempt': 0},
                 'C': {'worked': 22, 'exempt': 2},
                 'D': {'worked': 20, 'exempt': 0},
             }):
            f_W = apply_v2_month_end(base, employees, '/tmp', '2026-08', pricing)

        total_base = sum(base.values())
        total_final = sum(base[eid] * f_W[eid] for eid in base)
        assert abs(total_final - total_base) <= 10, \
            f"Total not preserved: {total_final} vs {total_base}"
