"""
tests/test_exporter.py
- 測試 HTML exporter 對假資料的輸出（含⑦ 滾動分布 SVG）
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib.exporter import render_html_report, _weights_display


# ────────── 假 analyze 結果 ──────────
def _fake_analyze() -> dict:
    return {
        'inputs': {
            'tickers': ['2330', '2317'],
            'shares': {'2330': 387, '2317': 5000},
            'weights': None,
            'pv': 7236096,
            'pv_source': 'mock',
            'pv_cost_text': '',
            'fees': {'fee_buy': 0.001425, 'fee_sell': 0.001425, 'tax_sell': 0.003, 'slippage': 0.001},
        },
        'common': {
            'mode': 'common',
            'metrics': {
                'start': '2010-01-04',
                'end': '2024-12-31',
                'years': 15.0,
                'total_return': 1.234,
                'cagr': 0.056,
                'mdd': -0.345,
                'volatility': 0.18,
                'sharpe': 0.42,
            },
        },
        'dynamic': {
            'mode': 'dynamic',
            'metrics': {
                'start': '2005-01-03',
                'end': '2024-12-31',
                'years': 20.0,
                'total_return': 2.5,
                'cagr': 0.067,
                'mdd': -0.40,
                'volatility': 0.20,
                'sharpe': 0.45,
            },
        },
        'full': {
            'mode': 'full',
            'metrics': {
                'start': '2000-01-04',
                'end': '2024-12-31',
                'years': 25.0,
                'total_return': 4.5,
                'cagr': 0.073,
                'mdd': -0.45,
                'volatility': 0.22,
                'sharpe': 0.48,
            },
        },
        'forecast': {
            'n': 10,
            'basis': 'common',
            'pv': 10_000_000,
            'rolling_count': 12,
            'r_count': 12,
            'percentiles': {
                'Bear': 0.02, 'Conservative': 0.05, 'Base': 0.08,
                'Optimistic': 0.12, 'Bull': 0.18,
            },
            'scenarios': [
                {'scenario': 'Bear (P10)', 'label': 'Bear', 'quantile': 0.10,
                 'cagr': 0.02, 'fv': 12_189_944, 'multiplier': 1.22},
                {'scenario': 'Conservative (P25)', 'label': 'Conservative', 'quantile': 0.25,
                 'cagr': 0.05, 'fv': 16_288_946, 'multiplier': 1.63},
                {'scenario': 'Base (P50)', 'label': 'Base', 'quantile': 0.50,
                 'cagr': 0.08, 'fv': 21_589_249, 'multiplier': 2.16},
                {'scenario': 'Optimistic (P75)', 'label': 'Optimistic', 'quantile': 0.75,
                 'cagr': 0.12, 'fv': 31_058_348, 'multiplier': 3.11},
                {'scenario': 'Bull (P90)', 'label': 'Bull', 'quantile': 0.90,
                 'cagr': 0.18, 'fv': 52_338_957, 'multiplier': 5.23},
            ],
            'rolling': [
                {'start': '2000-01-04', 'end': '2010-01-04', 'years': 10.0, 'cagr': 0.05},
                {'start': '2001-01-04', 'end': '2011-01-04', 'years': 10.0, 'cagr': 0.04},
                {'start': '2002-01-04', 'end': '2012-01-04', 'years': 10.0, 'cagr': 0.03},
                {'start': '2003-01-04', 'end': '2013-01-04', 'years': 10.0, 'cagr': 0.06},
                {'start': '2004-01-04', 'end': '2014-01-04', 'years': 10.0, 'cagr': 0.07},
                {'start': '2005-01-04', 'end': '2015-01-04', 'years': 10.0, 'cagr': 0.10},
                {'start': '2006-01-04', 'end': '2016-01-04', 'years': 10.0, 'cagr': 0.08},
                {'start': '2007-01-04', 'end': '2017-01-04', 'years': 10.0, 'cagr': 0.12},
                {'start': '2008-01-04', 'end': '2018-01-04', 'years': 10.0, 'cagr': 0.09},
                {'start': '2009-01-04', 'end': '2019-01-04', 'years': 10.0, 'cagr': 0.06},
                {'start': '2010-01-04', 'end': '2020-01-04', 'years': 10.0, 'cagr': 0.11},
                {'start': '2011-01-04', 'end': '2021-01-04', 'years': 10.0, 'cagr': 0.15},
            ],
        },
        'history': {
            'overview': {
                # 驗收標準 #6 新欄位
                'start': '2000-01-04',
                'end': '2024-12-31',
                'rows': 6000,
                'first_close': 50.0,
                'last_close': 600.0,
                # 舊欄位（compatibility）
                'stocks': 2,
                'min_years': 14.5,
                'median_years': 17.2,
                'max_years': 20.0,
            },
            'per_stock': {
                '2330': {
                    'years': 20.0, 'start': '2000-01-04', 'end': '2024-12-31',
                    'rows': 6000, 'first_close': 50.0, 'last_close': 600.0,
                },
                '2317': {
                    'years': 14.5, 'start': '2005-01-03', 'end': '2024-12-31',
                    'rows': 5000, 'first_close': 30.0, 'last_close': 200.0,
                },
            },
            'all_per_stock': {'2330': 20.0, '2317': 14.5},
        },
    }


def test_html_renders_without_error():
    html = render_html_report(_fake_analyze(), profile_name='liyu_stock')
    assert '<html' in html.lower() or '<!doctype' in html.lower()
    assert 'liyu_stock' in html
    assert 'Base' in html
    assert '10,000,000' in html or '10000000' in html


def test_html_includes_rolling_chart_svg():
    """⑦ 滾動 N 年收益分布圖（純 SVG）必須內嵌在 Section 三"""
    html = render_html_report(_fake_analyze(), profile_name='liyu_stock')
    assert '<svg' in html, 'HTML 報告應含 <svg> 圖（⑦ 滾動分布）'
    assert 'Bear P10' in html, '應標示 Bear P10 分位線'
    assert 'Bull P90' in html, '應標示 Bull P90 分位線'
    assert '<polyline' in html, '應有滾動 CAGR 主折線'


def test_html_rolling_chart_xaxis_spans_full_range():
    """F3 regression: rolling chart X 軸必須覆蓋 rolling 資料完整範圍

    過去 bug: chart 只顯示最近 21 個月（forecast.rolling 被截斷時 SVG 也跟著短）
    驗收:
      1. forecast.rolling span ≥ N 年（upstream 資料正確）
      2. SVG x 軸 first tick ≤ rolling[0].end（start 對齊）
      3. SVG x 軸 last tick 在 rolling 範圍末端附近（取樣容差 ±50% span）
      4. SVG span ≥ N 年（不該被截斷到只有幾個月）
    """
    import re
    from datetime import date
    fake = _fake_analyze()
    rolling = fake['forecast']['rolling']
    n = fake['forecast']['n']
    # 1. upstream data check: rolling span ≥ N 年
    rolling_first = date.fromisoformat(rolling[0]['end'])
    rolling_last = date.fromisoformat(rolling[-1]['end'])
    rolling_span = (rolling_last - rolling_first).days / 365.25
    assert rolling_span >= n, (
        f'forecast.rolling span {rolling_span:.2f} 年少於 N={n},'
        f'upstream 資料被截斷 (F3 root cause)'
    )
    # 2-4. SVG tick 檢查
    html = render_html_report(fake, profile_name='liyu_stock')
    ticks = re.findall(
        r'<text[^>]*fill="#475569"[^>]*>(20\d\d-\d\d-\d\d)</text>', html
    )
    assert len(ticks) >= 2, f'SVG 應至少有 2 個 X 軸 tick,實際 {len(ticks)}'
    first = date.fromisoformat(ticks[0])
    last = date.fromisoformat(ticks[-1])
    # 2. first tick 對齊 rolling 起點
    assert first <= rolling_first, (
        f'X 軸第一個 tick {first} 不應晚於 rolling[0].end {rolling_first}'
    )
    # 3. last tick 需位於 rolling 末端 ±50% span 內（取樣容差）
    span_days = (rolling_last - rolling_first).days
    tolerance = span_days * 0.5
    last_within = abs((last - rolling_last).days) <= tolerance
    assert last_within, (
        f'X 軸最後 tick {last} 偏離 rolling[-1].end {rolling_last} 超過 50% span'
    )
    # 4. SVG span ≥ N 年（浮點容差 0.05 年 ≈ 18 天,避免 9.998 < 10 這種慘案）
    svg_span = (last - first).days / 365.25
    assert svg_span >= n - 0.05, (
        f'X 軸 span {svg_span:.2f} 年少於 N={n} 年,代表 chart 被截斷'
    )


def test_html_n_year_filter_in_monthly_table():
    """Phase 6 (Item 1, 2): 明細表限定 N 年 + 頂部標註 N / 實際起訖 / 實際年數

    Item 1: 明細表僅包含 N 年資料,不混進全歷史。
    Item 2: 明細表頁面標註實際起訖、實際年數、N 參數。
    """
    from datetime import date
    import pandas as pd
    fake = _fake_analyze()
    # 造 fake daily returns: 0050 + 2330 各 5 年
    end = pd.Timestamp('2024-12-31')
    start = end - pd.DateOffset(years=5)
    days = pd.bdate_range(start, end, freq='B')
    fake['meta'] = {
        'daily_returns_by_ticker': {
            '0050': [{'date': d.strftime('%Y-%m-%d'), 'ret': 0.0005} for d in days],
            '2330': [{'date': d.strftime('%Y-%m-%d'), 'ret': 0.0010} for d in days],
        },
        'start_date': start.strftime('%Y-%m-%d'),
        'end_date': end.strftime('%Y-%m-%d'),
    }
    fake['forecast'] = {'n': 2, 'basis': 'common', 'pv': 10_000_000}
    html = render_html_report(fake, profile_name='liyu_stock')
    # Item 2: header annotation 應含 N + 實際起訖 + 實際年數
    assert 'N = 2 年' in html, '明細表 header 應標示 N=2 年'
    assert '實際起訖' in html, '明細表 header 應標示實際起訖'
    assert '實際年數' in html, '明細表 header 應標示實際年數'
    # Item 1: actual_start 不應比 5 年前還早(表示已 N-year slice)
    import re
    m = re.search(r'實際起訖：<b>(\d{4}-\d{2}-\d{2})', html)
    assert m, '應有「實際起訖」字樣'
    actual_start = date.fromisoformat(m.group(1))
    earliest = (end - pd.DateOffset(years=2)).date()
    assert actual_start >= earliest, (
        f'明細表起日 {actual_start} 應在 N=2 年 cutoff {earliest} 之後'
        f'（全歷史 5 年混進明細表 → Item 1 不及格）'
    )


def test_html_section_two_hoisted_dates_when_same():
    """當三模式的 start/end 都相同,起訖日應提高至上一階（不重複出現在每個模式）"""
    fake = _fake_analyze()
    # 讓三模式共用同一組日期
    common_dates = {'start': '2010-01-04', 'end': '2024-12-31'}
    for m in ('common', 'dynamic', 'full'):
        fake[m]['metrics'].update(common_dates)
    html = render_html_report(fake, profile_name='liyu_stock')
    # 上方應有「共用起訖日」區塊
    assert '三模式共用' in html, '起訖日應提高至上一階顯示(三模式共用標記)'
    # 每個模式的 KPI 不應再重複列「開始日期」「結束日期」(因已 hoist)
    # 計算「開始日期」字串在 KPI grid 區塊出現次數 — 應只出現 1 次(在共用區塊)
    kpi_section = html.split('三、')[0]  # Section 三 之前的內容
    start_label_count = kpi_section.count('開始日期')
    end_label_count = kpi_section.count('結束日期')
    assert start_label_count == 1, f'「開始日期」應只出現 1 次(共用),實際 {start_label_count}'
    assert end_label_count == 1, f'「結束日期」應只出現 1 次(共用),實際 {end_label_count}'


def test_html_section_two_fallback_when_dates_differ():
    """當三模式日期不同,起訖日退回各模式 KPI 內顯示(向後相容)"""
    fake = _fake_analyze()
    # 三模式日期刻意不同(沿用 _fake_analyze 的預設差異)
    html = render_html_report(fake, profile_name='liyu_stock')
    kpi_section = html.split('三、')[0]
    # 三模式日期不同 → 開始日期應出現 3 次(每模式一次)
    start_label_count = kpi_section.count('開始日期')
    assert start_label_count >= 3, (
        f'日期不同時應退回各模式顯示,預期「開始日期」≥3 次,實際 {start_label_count}'
    )


# ────────── B4: v2 Monte Carlo + Sequence Risk section ──────────
def test_html_renders_mc_section_when_present():
    """B4: 當 analyze.monte_carlo 有資料,應渲染「三·五、Monte Carlo 模擬」區塊"""
    fake = _fake_analyze()
    fake['monte_carlo'] = {
        'summary': {
            'median_final': 50_000_000,
            'mean_final': 55_000_000,
            # Phase 6 (Item 5): F1 完整分位數 + std
            'p5_final': 12_000_000,
            'p10_final': 18_000_000,
            'p25_final': 32_000_000,
            'p50_final': 50_000_000,
            'p75_final': 72_000_000,
            'p90_final': 95_000_000,
            'p95_final': 110_000_000,
            'std_final': 25_000_000,
            'prob_above_initial': 0.85,
            'prob_zero_or_negative': 0.05,
            'survival_to_horizon': 0.95,
        },
        'n_simulations': 1000,
        'horizon_years': 20,
    }
    html = render_html_report(fake, profile_name='liyu_stock')
    assert '五、Monte Carlo 模擬' in html, '應渲染 F1+F2 區塊標題'
    assert 'F1 Monte Carlo' in html, '應有 F1 子區塊'
    assert '50,000,000' in html, '應顯示中位終值'
    assert '85.00%' in html, '應顯示 prob_above_initial'


def test_html_renders_sr_section_when_present():
    """B4: 當 analyze.sequence_risk 有資料,應渲染 F2 子區塊"""
    fake = _fake_analyze()
    fake['sequence_risk'] = {
        'survival_rate': 0.85,
        'median_final_balance': 25_000_000,
        'success_rate_by_age': {
            '70': 0.95, '75': 0.90, '80': 0.85, '85': 0.80, '90': 0.70,
        },
    }
    html = render_html_report(fake, profile_name='liyu_stock')
    assert 'F2 Sequence Risk' in html, '應有 F2 子區塊'
    assert '85.00%' in html, '應顯示 survival_rate'
    assert '25,000,000' in html, '應顯示中位終值餘額'
    # survival_rate ≥ 0.7 應是綠色
    assert '#1e8e3e' in html, 'survival ≥ 0.7 應使用綠色'


def test_html_sr_low_survival_uses_red():
    """F2 survival < 0.5 應是紅色"""
    fake = _fake_analyze()
    fake['sequence_risk'] = {
        'survival_rate': 0.30,
        'median_final_balance': 0,
        'success_rate_by_age': {},
    }
    html = render_html_report(fake, profile_name='liyu_stock')
    assert '#b42318' in html, 'survival < 0.5 應使用紅色'


def test_html_sr_dynamic_age_columns_and_ruin_dist():
    """Phase 2A + 2B 驗收:
    - 動態年齡列依 retirement_age + 5k 取代 hardcoded 70-90
    - ruin_age_distribution 渲染 histogram + 零破產訊息
    """
    fake = _fake_analyze()
    fake['sequence_risk'] = {
        'survival_rate': 0.75,
        'median_final_balance': 12_000_000,
        'success_rate_by_age': {
            '65': 0.98, '70': 0.95, '75': 0.90, '80': 0.80, '85': 0.70,
        },
        'config': {
            'retirement_age': 60,
            'horizon_years': 30,    # → 65, 70, 75, 80, 85, 90
        },
    }
    html = render_html_report(fake, profile_name='liyu_stock')
    # Phase 2A 動態年齡:依 horizon/5 + retirement_age 產生 65-90
    assert '65 歲存活率' in html, '應有 65 歲動態列'
    assert '90 歲存活率' in html, '應有 90 歲動態列'
    assert '95.00%' in html, '應有 70 歲存活率數值'
    # Phase 2B: ruin_age_distribution 應渲染
    fake['sequence_risk']['ruin_age_distribution'] = [75, 75, 80, 82, 85]
    html = render_html_report(fake, profile_name='liyu_stock')
    assert '破產年齡分布' in html, '應渲染破產年齡分布區塊'
    assert '75 歲破產' in html, '應有 75 歲破產'
    assert '85 歲破產' in html, '應有 85 歲破產'
    # 75 歲 2/5 = 40%
    assert '40.00%' in html, '應渲染 40% 機率'


def test_html_sr_zero_ruin_green_message():
    """Phase 2B: ruin_age_distribution = [] 應顯示 ✅ 零破產訊息"""
    fake = _fake_analyze()
    fake['sequence_risk'] = {
        'survival_rate': 1.0,
        'median_final_balance': 50_000_000,
        'success_rate_by_age': {'65': 1.0, '70': 1.0, '75': 1.0, '80': 1.0, '85': 1.0, '90': 1.0},
        'ruin_age_distribution': [],
        'config': {'retirement_age': 60, 'horizon_years': 30, 'n_simulations': 1000},
    }
    html = render_html_report(fake, profile_name='liyu_stock')
    assert '沒有任何路徑提早破產' in html, '零破產應顯示綠色訊息'


def test_html_skips_mc_sr_section_when_none():
    """向後相容: 當 mc/sr 都為 None, 不渲染新區塊"""
    fake = _fake_analyze()
    fake['monte_carlo'] = None
    fake['sequence_risk'] = None
    html = render_html_report(fake, profile_name='liyu_stock')
    assert '三·五、Monte Carlo 模擬' not in html, 'mc/sr 都 None 應跳過區塊'


def test_html_renders_risk_metrics_section():
    """B4 加碼: analyze.risk_metrics 有資料 → 渲染「三·六、風險指標」區塊（F3 + F6）"""
    fake = _fake_analyze()
    fake['risk_metrics'] = {
        'var_cvar': {
            'var_1d_95': -0.0137,
            'var_1d_99': -0.0228,
            'var_21d_95': -0.05,
            'var_21d_99': -0.08,
            'var_252d_95': -0.20,
            'var_252d_99': -0.30,
            'cvar_1d_95': -0.0228,
            'cvar_1d_99': -0.0350,
            'cvar_21d_95': -0.07,
            'cvar_21d_99': -0.11,
            'cvar_252d_95': -0.27,
            'cvar_252d_99': -0.40,
            'method': 'historical',
        },
        'sharpe': {
            'sharpe_with_rf': 0.666,
            'sharpe_rf_0': 0.764,
            'rf_used': 0.015,
            'rf_daily_used': 0.0000595,
        },
    }
    html = render_html_report(fake, profile_name='liyu_stock')
    assert '七、風險指標' in html, '應渲染 F3+F6 區塊標題'
    assert 'F3 VaR' in html, '應有 F3 子區塊'
    assert 'F6 Sharpe' in html, '應有 F6 子區塊'
    assert '1.5%' in html, '應顯示 rf_used=1.5%'
    assert '0.666' in html, '應顯示 sharpe_with_rf'
    assert '-1.37%' in html or '-13.70%' in html, '應顯示 VaR 1d 95%(负值)'


def test_html_skips_risk_metrics_when_none():
    """向後相容: risk_metrics 為 None 應跳過區塊"""
    fake = _fake_analyze()
    fake['risk_metrics'] = None
    html = render_html_report(fake, profile_name='liyu_stock')
    assert '三·六、風險指標' not in html, 'risk_metrics None 應跳過區塊'


# ────────── Regression: BM 對照組 None metric 值（elhomeo + N=20 的 bug）──────────
def test_html_benchmark_with_none_metrics_renders():
    """Regression test: 當 bm.metrics.* 為 None, 報告仍能產生, 不噴 TypeError。
    Bug 2026-08-27: 主人用 elhomeo_stock.csv + N=20 計算成功, 產 HTML 失敗
    'must be real number, not str'。safe_pct/safe_float 在 None 時回 '—' (str),
    後續 '%.2f'|format('—') 壞掉。"""
    fake = _fake_analyze()
    fake['benchmark'] = {
        'ticker': '0050',
        'metrics': {
            'start': '2010-01-04',
            'end': '2024-12-31',
            'years': 15.0,
            'total_return': 1.5,
            'cagr': None,     # ← 主要缺失值
            'mdd': -0.30,
            'volatility': None,  # ← 主要缺失值
            'sharpe': 0.5,
        },
    }
    # 應不拋 TypeError
    html = render_html_report(fake, profile_name='elhomeo_stock')
    assert '<html' in html.lower() or '<!doctype' in html.lower()
    # None 值應顯示 '—', 不是 'nan' 或 'None'
    assert '—' in html, '應顯示 em-dash 給 None 值'
    # 不應出現字串 'None' 漏到 HTML
    assert '>None<' not in html, '不應出現裸字串 None 在表格 cell 中'


def test_html_benchmark_all_none_metrics_renders():
    """更極端: 全部 metric 為 None 也不能壞"""
    fake = _fake_analyze()
    fake['benchmark'] = {
        'ticker': '0050',
        'metrics': {
            'start': None, 'end': None, 'years': None,
            'total_return': None, 'cagr': None, 'mdd': None,
            'volatility': None, 'sharpe': None,
        },
    }
    html = render_html_report(fake, profile_name='elhomeo_stock')
    assert '<html' in html.lower() or '<!doctype' in html.lower()
    assert '>None<' not in html


def test_html_benchmark_with_real_numbers_still_works():
    """正向: 真實數字照舊顯示 (例如 volatility=0.18 → 18.00%)"""
    fake = _fake_analyze()
    fake['benchmark'] = {
        'ticker': '0050',
        'metrics': {
            'start': '2010-01-04',
            'end': '2024-12-31',
            'years': 15.0,
            'total_return': 1.5,
            'cagr': 0.08,
            'mdd': -0.35,
            'volatility': 0.18,
            'sharpe': 0.42,
        },
    }
    html = render_html_report(fake, profile_name='elhomeo_stock')
    assert '18.00%' in html, 'volatility 0.18 應顯示 18.00%'
    assert '8.00%' in html, 'cagr 0.08 應顯示 8.00%'
    assert '0.420' in html, 'sharpe 0.42 應顯示 0.420'


# ───── Phase 6B regression tests ─────

def test_html_f1_includes_extended_percentiles_p5_p25_p75_p95_std():
    """Phase 6 (Item 5): F1 表格必須含 P5/P25/P75/P95 + 標準差"""
    fake = _fake_analyze()
    fake['monte_carlo'] = {
        'summary': {
            'median_final': 50_000_000,
            'mean_final': 55_000_000,
            'p5_final': 12_000_000,
            'p10_final': 18_000_000,
            'p25_final': 32_000_000,
            'p50_final': 50_000_000,
            'p75_final': 72_000_000,
            'p90_final': 95_000_000,
            'p95_final': 110_000_000,
            'std_final': 25_000_000,
            'prob_above_initial': 0.85,
            'prob_zero_or_negative': 0.05,
            'survival_to_horizon': 0.95,
        },
        'n_simulations': 1000,
        'horizon_years': 20,
    }
    html = render_html_report(fake, profile_name='liyu_stock')
    assert 'P5（極端下限）' in html, 'F1 應顯示 P5'
    assert 'P25（保守下限）' in html, 'F1 應顯示 P25'
    assert 'P75（樂觀上限）' in html, 'F1 應顯示 P75'
    assert 'P95（極端上限）' in html, 'F1 應顯示 P95'
    assert '標準差' in html, 'F1 應顯示標準差'


def test_html_f2_includes_earliest_ruin_age_and_ruin_rate():
    """Phase 6 (Item 7): F2 表格必須含「破產率」+「最早破產年齡」"""
    fake = _fake_analyze()
    fake['sequence_risk'] = {
        'survival_rate': 0.65,
        'ruin_rate': 0.35,
        'earliest_ruin_age': 78,
        'median_final_balance': 8_000_000,
        'ruin_age_distribution': [78, 80, 82, 85],
        'success_rate_by_age': {'65': 1.0, '70': 0.95, '75': 0.85, '80': 0.60, '85': 0.30},
        'config': {'retirement_age': 60, 'horizon_years': 30, 'n_simulations': 1000,
                   'current_age': 55, 'retirement_end_age': 90},
    }
    html = render_html_report(fake, profile_name='liyu_stock')
    assert '破產率（任一年末資產 ≤ 0）' in html, 'F2 應顯示破產率'
    assert '最早破產年齡' in html, 'F2 應顯示最早破產年齡 row label'
    assert '78 歲' in html, 'F2 應顯示 78 歲最早破產'


def test_html_f2_no_ruin_shows_unbroken_message():
    """Phase 6 (Item 7): 沒有破產時,顯示「未破產」訊息 + 預設 horizon 終點"""
    fake = _fake_analyze()
    fake['sequence_risk'] = {
        'survival_rate': 1.0,
        'ruin_rate': 0.0,
        'earliest_ruin_age': None,
        'median_final_balance': 60_000_000,
        'ruin_age_distribution': [],
        'success_rate_by_age': {'65': 1.0, '70': 1.0, '75': 1.0, '80': 1.0, '85': 1.0, '90': 1.0},
        'config': {'retirement_age': 60, 'horizon_years': 30, 'n_simulations': 1000,
                   'current_age': 55, 'retirement_end_age': 90},
    }
    html = render_html_report(fake, profile_name='liyu_stock')
    assert '未破產' in html, '零破產應顯示「未破產」訊息'
    assert '90 歲' in html, '零破產應顯示 retirement_end_age=90'


def test_html_sample_stats_section_shows_valid_excluded_min_max():
    """Phase 6 (Item 3): 明細表標註「有效/排除/最短最長持有年數」"""
    fake = _fake_analyze()
    fake['forecast']['sample_stats'] = {
        'valid_count': 12,
        'excluded_count': 2,
        'min_actual_years': 9.8,
        'max_actual_years': 10.5,
    }
    fake['forecast']['n'] = 10
    html = render_html_report(fake, profile_name='liyu_stock')
    assert '有效樣本數' in html, '應顯示「有效樣本數」'
    assert '排除樣本數' in html, '應顯示「排除樣本數」'
    assert '最短實際持有年數' in html, '應顯示「最短實際持有年數」'
    assert '最長實際持有年數' in html, '應顯示「最長實際持有年數」'


def test_html_rolling_chart_xaxis_definition_annotation():
    """Phase 6 (Item 4): rolling chart 必須標註 X 軸定義"""
    from datetime import date, timedelta
    fake = _fake_analyze()
    # 補 forecast.rolling 讓 SVG render,annotation 才會出現在 HTML
    fake['forecast']['rolling'] = [
        {'start': (date(2014, 1, 1) + timedelta(days=365*i)).isoformat(),
         'end': (date(2024, 1, 1) + timedelta(days=365*i)).isoformat(),
         'years': 10.0, 'cagr': 0.05 + 0.001*i}
        for i in range(11)
    ]
    fake['forecast']['percentiles'] = {
        'Bear': 0.02, 'Conservative': 0.05, 'Base': 0.08,
        'Optimistic': 0.12, 'Bull': 0.18,
    }
    html = render_html_report(fake, profile_name='liyu_stock')
    assert 'X 軸 = 每一筆滾動 N 年樣本的「持有期間結束日」' in html, \
        '應標註 X 軸 = 持有期間結束日'
    assert '不是時間序列' in html, '應說明「不是時間序列」避免誤讀'


# ───── Phase 6D regression tests ─────

def test_html_f1_f2_dual_track_visual_split():
    """Phase 6 (Item 9): F1/F2 必須以視覺 badge 拆分"""
    fake = _fake_analyze()
    fake['monte_carlo'] = {
        'summary': {
            'median_final': 50_000_000,
            'mean_final': 55_000_000,
            'p5_final': 12_000_000, 'p10_final': 18_000_000,
            'p25_final': 32_000_000, 'p50_final': 50_000_000,
            'p75_final': 72_000_000, 'p90_final': 95_000_000, 'p95_final': 110_000_000,
            'std_final': 25_000_000,
            'prob_above_initial': 0.85, 'prob_zero_or_negative': 0.05,
            'survival_to_horizon': 0.95,
        },
        'n_simulations': 1000, 'horizon_years': 20,
    }
    fake['sequence_risk'] = {
        'survival_rate': 0.85,
        'ruin_rate': 0.15,
        'earliest_ruin_age': None,
        'median_final_balance': 25_000_000,
        'success_rate_by_age': {'65': 1.0, '70': 0.95, '75': 0.85},
        'config': {'retirement_age': 60, 'horizon_years': 30, 'n_simulations': 1000,
                   'current_age': 55, 'retirement_end_age': 90},
    }
    html = render_html_report(fake, profile_name='liyu_stock')
    assert 'F1 — 純投資累積模型' in html, '應有 F1 視覺 badge'
    assert 'F2 — 退休提款 Sequence Risk 模型' in html, '應有 F2 視覺 badge'
    assert '【雙軌模型】' in html, 'heading 應標註【雙軌模型】'


def test_html_survival_curve_svg_present_when_sr_data():
    """Phase 6 (Item 10): F2 必須有存活率 vs 年齡 SVG 圖"""
    fake = _fake_analyze()
    fake['sequence_risk'] = {
        'survival_rate': 0.85,
        'median_final_balance': 25_000_000,
        'success_rate_by_age': {'65': 1.0, '70': 0.95, '75': 0.85, '80': 0.70, '85': 0.50, '90': 0.30},
        'config': {'retirement_age': 60, 'horizon_years': 30, 'n_simulations': 1000,
                   'current_age': 55, 'retirement_end_age': 90},
    }
    html = render_html_report(fake, profile_name='liyu_stock')
    assert '退休資產存活率 vs 年齡' in html, '應有存活率曲線 heading'
    assert '<svg' in html and '<polyline' in html, '應有 SVG 折線'


def test_html_survival_curve_svg_absent_when_no_sr():
    """Phase 6 (Item 10): 沒有 SR 資料時,不顯示曲線"""
    fake = _fake_analyze()
    html = render_html_report(fake, profile_name='liyu_stock')
    assert '退休資產存活率 vs 年齡' not in html, '沒 SR 資料不應有曲線 heading'


def test_html_mdd_detail_includes_peak_trough_recovery():
    """Phase 6 (Item 11): MDD 詳細表必須含 Peak / Trough / Recovery Date"""
    fake = _fake_analyze()
    # 灌 common.metrics 的 MDD 詳細
    fake['common']['metrics'].update({
        'mdd': -0.35,
        'mdd_peak_date': '2017-08-28',
        'mdd_trough_date': '2018-12-31',
        'mdd_recovery_date': '2019-06-30',
        'mdd_drawdown_days': 490,
        'mdd_recovery_days': 181,
    })
    html = render_html_report(fake, profile_name='liyu_stock')
    assert 'MDD 詳細（Peak / Trough / Recovery）' in html, '應有 MDD 詳細 heading'
    assert 'Peak Date（高點）' in html, '應顯示 Peak Date label'
    assert 'Trough Date（低點）' in html, '應顯示 Trough Date label'
    assert 'Recovery Date（回復點）' in html, '應顯示 Recovery Date label'
    assert '2017-08-28' in html, '應顯示 peak_date 值'
    assert '2018-12-31' in html, '應顯示 trough_date 值'
    assert '2019-06-30' in html, '應顯示 recovery_date 值'
    assert '490' in html, '應顯示 drawdown_days 值'
    assert '181' in html, '應顯示 recovery_days 值'


def test_html_mdd_detail_shows_unrecovered_when_no_recovery():
    """Phase 6 (Item 11): Recovery Date 為 None 時應顯示「未回復」"""
    fake = _fake_analyze()
    fake['common']['metrics'].update({
        'mdd': -0.50,
        'mdd_peak_date': '2010-01-01',
        'mdd_trough_date': '2024-12-31',
        'mdd_recovery_date': None,
        'mdd_drawdown_days': 5478,
        'mdd_recovery_days': None,
    })
    html = render_html_report(fake, profile_name='liyu_stock')
    assert '未回復（仍在回撤中）' in html, '未回復時應顯示提示'
    assert '未回復)' in html, '回復天數應顯示「未回復」'


# ────────── v3.1.2: 此次權重標註（filter + HTML 渲染）──────────

def test_weights_display_filter_market_cap_drops_smallest():
    """v3.1.2: market_cap 來源 → 格式 TICKER:0.XXX，去掉最小一筆"""
    analyze = {
        'effective_weights': {
            '2330': 0.3289, '2885': 0.2708, '2412': 0.1863,
            '0050': 0.1157, '00631L': 0.0489, '0056': 0.0218,
            '2881': 0.0148, '2891': 0.0092, '2002': 0.0036,
        },
        'weights_source': 'market_cap',
    }
    out = _weights_display(analyze)
    # 大到小排序 + 去最小（2002:0.004），應該是 8 個
    assert out.startswith('（市值加權總計為1）'), f'source text 應為「市值加權總計為1」，got: {out}'
    assert '2330:0.329' in out, f'應有 2330:0.329，got: {out}'
    assert '2885:0.271' in out, f'應有 2885:0.271，got: {out}'
    assert '2891:0.009' in out, f'應有 2891:0.009，got: {out}'
    assert '2002' not in out, f'最小一筆 2002 應被去掉，got: {out}'


def test_weights_display_filter_user_input_kept():
    """v3.1.2: user 來源 → 顯示「使用者自訂」標籤
    注：只有 2 筆會去掉最小（只剩 2330）；換成 3 筆測才會保留 2317
    """
    analyze = {
        'effective_weights': {'2330': 0.7, '2317': 0.2, '0050': 0.1},
        'weights_source': 'user',
    }
    out = _weights_display(analyze)
    assert '使用者自訂' in out
    assert '2330:0.700' in out
    assert '2317:0.200' in out
    assert '0050' not in out, f'最小一筆 0050 應被去掉，got: {out}'


def test_weights_display_filter_single_ticker_no_drop():
    """v3.1.2: 只有 1 筆時不去掉（保留唯一的）"""
    analyze = {
        'effective_weights': {'2330': 1.0},
        'weights_source': 'user',
    }
    out = _weights_display(analyze)
    assert '2330:1.000' in out
    assert '使用者自訂' in out


def test_weights_display_filter_empty_uses_dash():
    """v3.1.2: 空權重 → 「—」"""
    analyze = {'effective_weights': {}, 'weights_source': 'equal'}
    out = _weights_display(analyze)
    assert out == '（等權重（fallback）） —'


def test_html_report_includes_weights_info_under_section_two():
    """v3.1.2: report.html ② 標題下應有此次權重標註"""
    fake = _fake_analyze()
    fake['effective_weights'] = {
        '2330': 0.6, '2317': 0.3, '0050': 0.1,
    }
    fake['weights_source'] = 'market_cap'
    html = render_html_report(fake, profile_name='liyu_stock')
    # 取此次權重段落，避免跟其他地方的數字混淆
    weights_block = html.split('此次權重：')[1].split('</p>')[0]
    assert '2330:0.600' in weights_block, f'2330:0.600 應在權重段，got: {weights_block}'
    assert '2317:0.300' in weights_block, f'2317:0.300 應在權重段，got: {weights_block}'
    assert '0050' not in weights_block, f'最小一筆 0050 應被去掉，got: {weights_block}'
    assert '市值加權總計為1' in weights_block, f'source label 應在權重段，got: {weights_block}'


def test_html_report_omits_weights_info_when_no_effective_weights():
    """v3.1.2: 沒有效權重時不渲染標註（向後相容）"""
    fake = _fake_analyze()  # 預設沒有 effective_weights
    html = render_html_report(fake, profile_name='liyu_stock')
    assert '此次權重：' not in html, '沒有效權重不應顯示此次權重標註'
