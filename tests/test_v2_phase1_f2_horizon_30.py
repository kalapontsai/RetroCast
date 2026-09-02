"""
tests/test_v2_phase1_f2_horizon_30.py
- Phase 1.5 驗收:F2 horizon 預設 30 年,跟 n_years 脫鉤
- 驗證項:
    1. app._compute_v2_extensions 在不傳 v2_horizon_years 時,使用 30 年(不是 n_years)
    2. config.horizon_years == 30
    3. config.current_age / retirement_age 來自 body
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib.finmind import FinMindClient
from app import _compute_v2_extensions


def _holdings_kadela():
    return [{'stock_id': '0050', 'shares': 1000, 'cost': 50}]


# ───────── 1. 預設 horizon = 30 ─────────
def test_f2_default_horizon_is_30_not_n_years():
    client = FinMindClient()
    body = {'profile': 'kadela_stock'}
    # 故意設 n_years=5,看 F2 還是用 30
    out = _compute_v2_extensions(body, client, _holdings_kadela(), 7_236_096, n_years=5)
    sr = out.get('sequence_risk')
    if sr is None:
        # 若 daily_returns 抓不到,測試 skip(本機沒 API key)
        import pytest
        pytest.skip(f'F2 skip:{out.get("_meta", {}).get("skip_reason", "unknown")}')
    cfg = sr['config']
    assert cfg['horizon_years'] == 30, f'F2 default horizon 應為 30,got {cfg["horizon_years"]}'
    assert cfg['current_age'] == 55, f'F2 default current_age 應為 55,got {cfg["current_age"]}'
    assert cfg['retirement_age'] == 60, f'F2 default retirement_age 應為 60,got {cfg["retirement_age"]}'
    assert cfg['retirement_end_age'] == 85, f'F2 retirement_end_age = current_age + horizon = 55+30 = 85,got {cfg["retirement_end_age"]}'


# ───────── 2. body 顯式傳 horizon + ages ─────────
def test_f2_explicit_horizon_overrides_default():
    client = FinMindClient()
    body = {
        'profile': 'kadela_stock',
        'v2_horizon_years': 35,
        'v2_current_age': 55,
        'v2_retirement_age': 60,
    }
    out = _compute_v2_extensions(body, client, _holdings_kadela(), 7_236_096, n_years=10)
    sr = out.get('sequence_risk')
    if sr is None:
        import pytest
        pytest.skip(f'F2 skip:{out.get("_meta", {}).get("skip_reason", "unknown")}')
    cfg = sr['config']
    assert cfg['horizon_years'] == 35
    assert cfg['current_age'] == 55
    assert cfg['retirement_age'] == 60


# ───────── 3. SPEC v2 default (60 → 90, 30 年) ─────────
def test_f2_spec_v2_default_60_to_90():
    client = FinMindClient()
    body = {
        'profile': 'kadela_stock',
        'v2_horizon_years': 30,
        'v2_current_age': 60,
        'v2_retirement_age': 60,
    }
    out = _compute_v2_extensions(body, client, _holdings_kadela(), 7_236_096, n_years=5)
    sr = out.get('sequence_risk')
    if sr is None:
        import pytest
        pytest.skip(f'F2 skip:{out.get("_meta", {}).get("skip_reason", "unknown")}')
    cfg = sr['config']
    assert cfg['horizon_years'] == 30
    assert cfg['current_age'] == 60
    assert cfg['retirement_age'] == 60
    assert cfg['retirement_end_age'] == 90
    # success_rate_by_age 應有 30 歲...60 歲 + 30 個 key (61-90),共 30 個
    sba = sr.get('success_rate_by_age', {})
    assert len(sba) == 30, f'應有 30 個年齡 key,got {len(sba)}'
