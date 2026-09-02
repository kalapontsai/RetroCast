"""Focused tests for portfolio-level risk and evidence-aware optimisation."""
import numpy as np
import pandas as pd

from lib.portfolio_optimization import build_optimization


def _prices(days=520):
    idx = pd.bdate_range('2020-01-01', periods=days)
    rng = np.random.default_rng(11)
    r = rng.normal(.0003, .01, (days, 7))
    out = pd.DataFrame(100 * np.cumprod(1 + r, axis=0), index=idx,
                       columns=[f'{i:04d}' for i in range(7)])
    out.loc[:idx[100], '0006'] = np.nan  # short history must remain a candidate
    return out


def test_short_history_is_retained_and_classified():
    p = _prices()
    tickers = list(p.columns)
    current = {t: 1 / 7 for t in tickers}
    result = build_optimization(p, current, {t: 1000 for t in tickers},
                                {t: 100 for t in tickers}, {t: 10 for t in tickers}, 5)
    assert '0006' in result['scores']
    assert result['scores']['0006']['classification'] in {'Partial N-Year', 'Short History'}
    assert result['dataset']['requested_n_years'] == 5


def test_portfolio_metrics_and_rebalance_are_actual_values():
    p = _prices()
    tickers = list(p.columns)
    current = {t: 1 / 7 for t in tickers}
    result = build_optimization(p, current, {t: 1000 for t in tickers},
                                {t: 100 for t in tickers}, {t: 10 for t in tickers}, 1,
                                fees={'commission': .001})
    assert result['status'] == 'SUCCESS'
    assert abs(sum(result['optimized']['weights']) - 1) < 1e-8
    assert all(k in result['optimized'] for k in ('volatility', 'mdd', 'sharpe', 'sortino', 'calmar', 'var', 'cvar'))
    assert 'cash_residual' in result['transaction_cost']
    assert all('actual_weight' in row for row in result['trades'])


def test_infeasible_weight_bounds_are_reported():
    idx = pd.bdate_range('2020-01-01', periods=100)
    p = pd.DataFrame(np.tile(np.linspace(100, 120, 100)[:, None], (1, 3)), index=idx, columns=['a', 'b', 'c'])
    current = {t: 1 / 3 for t in p.columns}
    result = build_optimization(p, current, {t: 1000 for t in p}, {t: 100 for t in p}, {t: 10 for t in p}, 1)
    assert result['status'] != 'SUCCESS'
    assert result['validation']['constraints_feasible'] is False
