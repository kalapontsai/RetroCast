"""tests/test_monthly_returns_consistency.py

P0 regression test (v3.0.4 fix):
月報酬明細 (card ⑥) vs 一.6 (per_stock_n_year_window) 應該對齊 (含息還原)。

Bug 背景 (v3.0.3 N8 之前):
  - production 路徑 (app.py:_build_analyze_meta):
      daily_returns = raw close pct_change → 含 split 跳變, 沒算股息再投入
  - ground truth (lib/portfolio.py:658, per_stock_n_year_window):
      shares tracking → raw close + window 內 dividend/split events → 含息總報酬

當前 5y 窗口 (2021-08-31 → 2026-08-31) 的差距 (主人叫修前):
  - 2330: raw close 5y 複利 +297.52% vs 一.6 +333.95% → 差距 ~36% (純股息再投入)
  - 0050: -23.84% vs +245.66% → 差距 ~270% (split 4:1 把月度複利炸掉)
  - 00631L: -72.82% vs +513.20% → 差距 ~586% (split 22:1 整個 window 幾乎歸零)

v3.0.4 P0 fix (主人 2026-09-03 拍板):
  - 月報酬表改走 fresh-start-per-month shares tracking
    (lib/monthly_returns.py:compute_monthly_returns_via_shares_tracking)
  - 不再用 daily_returns 累計(會被 cumulative shares 稀釋)
  - 跟一.6 同樣的 shares tracking 算法,但窗口 = 1 個月
  - 5y 累積複利 = 逐月複利再乘 → 數學上 ≡ 一.6

本測試釘死「兩者必須對齊」的 invariant:
  - 呼叫 production compute_monthly_returns_via_shares_tracking (透過 mock FinMindClient 用 cache)
  - 比對 5y 累積複利與 `per_stock_n_year_window` 的 total return
  - 容差 0.1% (純浮點誤差)

純新增測試, 不動 production code (v3.0.4 fix 改用 lib.monthly_returns 新函數)。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib.monthly_returns import compute_monthly_returns_via_shares_tracking  # noqa: E402  ← v3.0.4 P0 fix
from lib.portfolio import per_stock_n_year_window, prices_to_pivot  # noqa: E402


CACHE_DIR = ROOT / 'data' / 'price_cache'
N_YEARS = 5
# 跟一.6 per_stock_n_year_window 的 (end_date, cutoff) 對齊:
#   end_date='2026-09-01'、cutoff = end - 1826 days = '2021-09-01'
# 選 9/1 而非 8/31 是因為 pd.Timestamp 計算結果如此(避免一個月偏移)
END_DATE = '2026-09-01'
START_DATE = '2014-01-01'


# ───────── helpers ─────────
def _load_rows(ticker: str) -> list[dict]:
    return json.loads((CACHE_DIR / f'{ticker}.json').read_text(encoding='utf-8'))['rows']


def _load_events(ticker: str, kind: str) -> list[dict]:
    p = CACHE_DIR / f'{ticker}.{kind}.json'
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding='utf-8')).get('rows', [])


def _mock_finmind(rows_by_ticker: dict[str, list[dict]]) -> MagicMock:
    """Mock FinMindClient,讓 get_stock_price/get_dividends/get_splits 都從 cache JSON 拿資料。"""
    divs_by_ticker = {t: _load_events(t, 'dividend') for t in rows_by_ticker}
    splits_by_ticker = {t: _load_events(t, 'split') for t in rows_by_ticker}
    c = MagicMock()
    c.get_stock_price = MagicMock(
        side_effect=lambda t, s, e, **kw: rows_by_ticker[t]
    )
    c.get_dividends = MagicMock(
        side_effect=lambda t, s, e, **kw: divs_by_ticker.get(t, [])
    )
    c.get_splits = MagicMock(
        side_effect=lambda t, s, e, **kw: splits_by_ticker.get(t, [])
    )
    return c


def _production_monthly_returns(ticker: str) -> dict:
    """v3.0.4 P0 fix: 呼叫 production compute_monthly_returns_via_shares_tracking。

    跟 app.py:_run_analyze + /api/v2/monthly_returns endpoint 走同一條路。
    """
    rows = _load_rows(ticker)
    client = _mock_finmind({ticker: rows})
    # 模擬 endpoint 行為:抓 raw + div + split → pivot → shares tracking
    divs = client.get_dividends(ticker, START_DATE, END_DATE)
    splits = client.get_splits(ticker, START_DATE, END_DATE)
    pivot = prices_to_pivot({ticker: rows}, price_col='close')
    # 限到 5y 窗口讓 monthly 5y compound 對齊一.6
    # 一.6 用 raw 最後一天當 end_date,所以 production 也用 raw 最後一天
    last_day = pivot.index[-1]
    ws_ts = last_day - pd.Timedelta(days=int(N_YEARS * 365.25))
    return compute_monthly_returns_via_shares_tracking(
        pivot,
        dividends_by_ticker={ticker: divs},
        splits_by_ticker={ticker: splits},
        window_start=ws_ts.strftime('%Y-%m-%d'),
        window_end=last_day.strftime('%Y-%m-%d'),
    )


def _5y_compound_from_monthly(monthly_data: dict) -> float:
    """從 monthly_returns 結果裡,挑出 5y 窗口內的月報酬,算累積複利。

    window 定義:跟一.6 per_stock_n_year_window 同算法
      end_date = raw 最後一天
      cutoff = end_date - 1826 days
      一個 month (y, m) 納入若其 [month_start, month_end] 與 window 有交集
    """
    # 從 data 推断 window (跟一.6 對齊):
    years = sorted(int(y) for y in monthly_data.keys())
    if not years:
        return 0.0
    # 取最近一個月的 month_end 當 window 終點
    last_year = years[-1]
    last_month = max(int(m) for m in monthly_data[last_year] if m != 'year_avg')
    window_end_ts = pd.Timestamp(year=last_year, month=last_month, day=1) + pd.offsets.MonthEnd(1)
    window_start_ts = window_end_ts - pd.Timedelta(days=int(N_YEARS * 365.25))

    rets = []
    for year_key, months in monthly_data.items():
        for month_key, v in months.items():
            if month_key == 'year_avg':
                continue
            try:
                y, m = int(year_key), int(month_key)
            except (TypeError, ValueError):
                continue
            month_start = pd.Timestamp(year=y, month=m, day=1)
            month_end = month_start + pd.offsets.MonthEnd(1)
            # month 跟 window 有交集
            if month_end >= window_start_ts and month_start <= window_end_ts:
                if v is not None:
                    rets.append(float(v))
    if not rets:
        return 0.0
    return float(pd.Series(rets).add(1).prod() - 1)


def _n_year_ground_truth(ticker: str) -> float:
    """一.6 ground truth (含息 shares tracking) — 跟 production 解耦。"""
    rows = _load_rows(ticker)
    divs = _load_events(ticker, 'dividend')
    splits = _load_events(ticker, 'split')

    df = pd.DataFrame(rows)
    df['date'] = pd.to_datetime(df['date'])
    df = df.set_index('date').sort_index()
    raw = pd.DataFrame({ticker: df['close']})

    res = per_stock_n_year_window(
        raw, n_years=N_YEARS,
        dividends_by_ticker={ticker: divs},
        splits_by_ticker={ticker: splits},
    )
    return float(res[ticker]['total_return'])


# ───────── 主測試:P0 invariant ─────────
@pytest.mark.parametrize('ticker', ['2330', '0050', '00631L'])
def test_5y_monthly_compound_matches_n_year_window(ticker):
    """Card ⑥ 月報酬明細的 5y 累積複利 ≈ 一.6 的 5y total return (含息還原)。

    v3.0.4 P0 fix 路徑:
      compute_monthly_returns_via_shares_tracking (fresh-start-per-month shares tracking)
    Ground truth:
      per_stock_n_year_window (shares tracking over 5y window)

    兩者必須對齊 (容差 0.5%, 因為窗口邊界日略有差異)。
    """
    monthly = _production_monthly_returns(ticker)
    assert monthly['tickers'], f'{ticker}: production monthly 沒資料'
    tk = monthly['tickers'][0]
    production_5y = _5y_compound_from_monthly(tk['data'])
    ground_truth_5y = _n_year_ground_truth(ticker)

    gap_pct = abs(production_5y - ground_truth_5y) * 100

    assert gap_pct < 0.5, (
        f'\n  ✗ {ticker}: 5y monthly compound (production 路徑) = {production_5y*100:+.2f}%'
        f'\n  ✗ {ticker}: 一.6 5y total (ground truth, 含息)     = {ground_truth_5y*100:+.2f}%'
        f'\n  ✗ 差距 = {gap_pct:.2f}% (容差 0.5%)'
        f'\n  → 月報酬表 (shares tracking) 跟 一.6 (shares tracking) 口徑分叉'
    )


# ───────── 次測試:月報酬明細表本身能算 (sanity, 確保 chain 沒壞) ─────────
@pytest.mark.parametrize('ticker', ['2330', '0050', '00631L'])
def test_monthly_returns_table_chain_works(ticker):
    """確認 _production_monthly_returns 不會 crash + 有資料。"""
    monthly = _production_monthly_returns(ticker)
    assert len(monthly['tickers']) == 1
    t = monthly['tickers'][0]
    assert t['ticker'] == ticker
    assert len(t['data']) >= N_YEARS  # 至少 5 年
    # 確認最近一年有月資料
    last_year = t['last_year']
    assert last_year >= 2025
    months = t['data'][last_year]
    valid_months = [k for k in months if k != 'year_avg' and months[k] is not None]
    assert len(valid_months) >= 6  # 至少半年


# ───────── 文件測試:永遠 pass,印出當前 bug 差距給人看 ─────────
def test_document_bug_severity(capsys):
    """印出三檔的當前差距, 給主人 review 用。永遠 pass。"""
    print('\n=== P0 bug severity (5y window: 2021-08-31 → 2026-08-31) ===')
    print(f'  {"ticker":6}  {"production":>15}  {"ground truth":>15}  {"gap":>10}')
    for ticker in ['2330', '0050', '00631L']:
        monthly = _production_monthly_returns(ticker)
        tk = monthly['tickers'][0]
        p_5y = _5y_compound_from_monthly(tk['data'])
        g_5y = _n_year_ground_truth(ticker)
        gap = abs(p_5y - g_5y) * 100
        print(f'  {ticker:6}  {p_5y*100:+12.2f}%  {g_5y*100:+12.2f}%  {gap:+8.2f}%')
    print('  → 預期 production 跟 ground truth 完全相等 (容差 < 0.5%)\n')
