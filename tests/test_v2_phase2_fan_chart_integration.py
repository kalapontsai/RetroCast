"""
tests/test_v2_phase2_fan_chart_integration.py
- Phase 2E 整合測試:fan chart SVG 進 template 後能正常渲染
- 驗證項:
    1. analyze 傳 percentile_bands + initial_balance → HTML 內含 fan_chart_svg
    2. percentile_bands 為空 → 不 crash,且 SVG placeholder 出現
    3. percentile_bands 缺 P95 → SVG 不渲染 P5-P95 帶但其他正常
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# 借用既有 fake_analyze 避免重造輪子(同檔案結構確保 template 不炸)
sys.path.insert(0, str(ROOT / 'tests'))
from test_exporter import _fake_analyze

from lib.exporter import render_html_report


def _make_fake_with_mc():
    fake = _fake_analyze()
    fake['monte_carlo'] = {
        'config': {'n_simulations': 1000, 'horizon_years': 30, 'initial_balance': 1_000_000},
        'percentile_bands': [
            {'percentile': p, 'year': y, 'value': 1_000_000 * (1 + 0.05 * y) * mult}
            for y in range(1, 31)
            for p, mult in [(5, 0.7), (25, 0.85), (50, 1.0), (75, 1.15), (95, 1.3)]
        ],
        'summary': {
            'median_final': 1_500_000, 'mean_final': 1_500_000,
            'p10_final': 800_000, 'p90_final': 2_800_000,
            'prob_above_initial': 0.65, 'prob_zero_or_negative': 0.05,
            'survival_to_horizon': 0.95,
        },
        'n_simulations': 1000,
        'horizon_years': 30,
        'success_rate': 0.85,
        'median_final_balance': 1_500_000,
    }
    return fake


# ─────── 1. percentile_bands → SVG 內嵌 ───────
def test_fan_chart_svg_embedded_in_html():
    html = render_html_report(_make_fake_with_mc(), profile_name='kadela_stock')
    # F1 區塊存在
    assert 'Monte Carlo' in html, 'F1 區塊應存在'
    assert '<svg' in html, 'fan chart 應輸出 SVG'
    assert 'stroke="#b42318"' in html, 'P50 中位線應渲染'
    assert 'P5-P95 (90%)' in html, 'legend 應渲染'
    assert 'P25-P75 (50%)' in html
    assert '初始 1,000,000' in html, '初始資產水平參考線'


# ─────── 2. 沒有 percentile_bands → placeholder ───────
def test_fan_chart_placeholder_when_no_bands():
    fake = _make_fake_with_mc()
    fake['monte_carlo']['percentile_bands'] = []
    html = render_html_report(fake, profile_name='kadela_stock')
    assert '無 fan chart 資料' in html, '無 bands 應顯示 placeholder'


# ─────── 3. 缺 P95 → P5-P95 帶不渲染但其他正常 ───────
def test_fan_chart_missing_p95_still_renders_rest():
    fake = _make_fake_with_mc()
    fake['monte_carlo']['percentile_bands'] = [
        {'percentile': p, 'year': 1, 'value': 1_000_000} for p in (5, 25, 50, 75)
    ]
    html = render_html_report(fake, profile_name='kadela_stock')
    # P5-P95 帶(沒有 P95)不渲染
    assert 'fill="#fbe5e5"' not in html, '缺 P95 不應渲染 P5-P95 帶'
    # P25-P75 仍應有
    assert 'fill="#f7c8c8"' in html
    # P50 線
    assert 'stroke="#b42318"' in html


# ─────── 4. mc 為 None → graceful,不渲染 fan chart ───────
def test_fan_chart_graceful_when_mc_is_none():
    fake = _make_fake_with_mc()
    fake['monte_carlo'] = None
    html = render_html_report(fake, profile_name='kadela_stock')
    # 整個 F1 區塊應跳過
    assert 'Monte Carlo' not in html, 'mc=None 應跳過 F1 區塊'
