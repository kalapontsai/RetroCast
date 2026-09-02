"""
tests/test_fan_chart.py
- Phase 2E 驗收:fan_chart.render_fan_chart_svg
- 驗證項:
    1. 沒有 percentile_bands → 回傳 placeholder SVG (不 crash)
    2. 完整 P5/P25/P50/P75/P95 → SVG 含 polygon (P5-P95) + polygon (P25-P75) + polyline (P50)
    3. 缺某個 percentile → 該帶不渲染,但其他仍正常
    4. initial_balance 傳入 → 顯示水平參考線
    5. SVG 寬度/視圖大小正確
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib.fan_chart import render_fan_chart_svg


def _full_bands(n_years: int = 30, initial: int = 1_000_000, growth: float = 0.05) -> list[dict]:
    """構造完整的 P5/P25/P50/P75/P95 bands (隨時間線性增長 + 隨機散布)"""
    bands = []
    for y in range(1, n_years + 1):
        median = initial * (1 + growth) ** y
        for p in (5, 25, 50, 75, 95):
            # 簡單模型:P95 比中位高 30%, P5 比中位低 30%
            if p == 95:
                v = median * 1.3
            elif p == 75:
                v = median * 1.15
            elif p == 50:
                v = median
            elif p == 25:
                v = median * 0.85
            else:  # p == 5
                v = median * 0.7
            bands.append({'percentile': p, 'year': y, 'value': v})
    return bands


# ─────── 1. 空資料不 crash ───────
def test_fan_chart_empty_returns_placeholder():
    svg = render_fan_chart_svg([])
    assert '<svg' in svg
    assert '無 fan chart 資料' in svg


# ─────── 2. 完整 bands ───────
def test_fan_chart_full_bands_renders_polygons_and_line():
    bands = _full_bands(30)
    svg = render_fan_chart_svg(bands, initial_balance=1_000_000)
    # P5-P95 帶
    assert 'fill="#fbe5e5"' in svg, '應有 P5-P95 最外帶'
    # P25-P75 帶
    assert 'fill="#f7c8c8"' in svg, '應有 P25-P75 中間帶'
    # P50 線
    assert 'stroke="#b42318"' in svg, '應有 P50 中位線'
    # 初始參考線
    assert '初始 1,000,000' in svg, '應有初始資產水平線標籤'
    assert 'polyline' in svg, '應有 polyline 元素'
    assert svg.count('<polygon') == 2, '應有 2 個 polygon (P5-P95 + P25-P75)'


# ─────── 3. 缺 P5 → P5-P95 帶不渲染,但其他仍正常 ───────
def test_fan_chart_missing_p5_still_renders_rest():
    bands = [b for b in _full_bands(30) if b['percentile'] != 5]
    svg = render_fan_chart_svg(bands, initial_balance=1_000_000)
    # 沒有 P5 → 應該只有 1 個 polygon (P25-P75),不是 2 個
    assert svg.count('<polygon') == 1, f'缺 P5 應只有 1 個 polygon,got {svg.count("<polygon")}'
    # P50 線仍有
    assert 'polyline' in svg
    assert 'stroke="#b42318"' in svg


# ─────── 4. 初始資產水平線 ───────
def test_fan_chart_initial_balance_line():
    bands = _full_bands(10)
    svg_with = render_fan_chart_svg(bands, initial_balance=2_000_000)
    svg_without = render_fan_chart_svg(bands, initial_balance=None)
    assert '初始 2,000,000' in svg_with
    assert '初始 2,000,000' not in svg_without


# ─────── 5. SVG 大小正確 ───────
def test_fan_chart_svg_size():
    svg = render_fan_chart_svg(_full_bands(15))
    assert 'viewBox="0 0 760 280"' in svg
    assert 'width="100%"' in svg
