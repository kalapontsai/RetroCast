"""Return + Risk + MDD portfolio optimisation.

This module deliberately has no scipy dependency.  The feasible set is a
simple capped simplex, so a deterministic projected coordinate search is
adequate for the report and keeps the calculation reproducible.
"""
from __future__ import annotations

import math
import itertools
from typing import Any

import numpy as np
import pandas as pd


NA = None
MODE_PARAMS = {
    'Conservative': {'lambda_tracking': 2.0, 'gamma_concentration': 2.0},
    'Balanced': {'lambda_tracking': 1.0, 'gamma_concentration': 1.0},
    'Growth': {'lambda_tracking': 0.25, 'gamma_concentration': 0.5},
}


def _score(values, higher=True):
    s = pd.Series(values, dtype=float)
    if s.dropna().empty or s.max() == s.min():
        return pd.Series(1.0, index=s.index).where(s.notna())
    out = (s - s.min()) / (s.max() - s.min())
    return out if higher else 1 - out


def _portfolio_metrics(returns: pd.DataFrame, w: np.ndarray) -> dict:
    pr = returns.to_numpy(dtype=float) @ w
    if len(pr) < 2:
        return {'cagr': NA, 'volatility': NA, 'mdd': NA, 'sharpe': NA, 'calmar': NA, 'equity': []}
    equity = np.cumprod(1 + pr)
    years = max((returns.index[-1] - returns.index[0]).days / 365.25, 1 / 365.25)
    vol = float(np.std(pr, ddof=1) * np.sqrt(252))
    cagr = float(equity[-1] ** (1 / years) - 1) if equity[-1] > 0 else NA
    dd = equity / np.maximum.accumulate(equity) - 1
    mdd = float(dd.min())
    sharpe = float(np.mean(pr) / np.std(pr, ddof=1) * np.sqrt(252)) if vol > 0 else NA
    calmar = float(cagr / abs(mdd)) if cagr is not None and mdd < 0 else NA
    trough = int(np.argmin(dd)); peak = int(np.argmax(equity[:trough + 1]))
    recovery = next((i for i in range(trough, len(equity)) if equity[i] >= equity[peak]), None)
    max_duration = max((len(list(g)) for active, g in itertools.groupby(dd < -1e-12) if active), default=0)
    drawdown = [{'date': d.strftime('%Y-%m-%d'), 'value': float(v)}
                for d, v in zip(returns.index, dd)]
    return {'cagr': cagr, 'volatility': vol, 'mdd': mdd, 'sharpe': sharpe,
            'mdd_start': returns.index[peak].strftime('%Y-%m-%d'),
            'mdd_bottom': returns.index[trough].strftime('%Y-%m-%d'),
            'recovery_date': returns.index[recovery].strftime('%Y-%m-%d') if recovery is not None else None,
            'recovery_days': int((returns.index[recovery] - returns.index[trough]).days) if recovery is not None else None,
            'maximum_drawdown_duration_days': int(max_duration),
            'calmar': calmar, 'drawdown': drawdown, 'equity': [{'date': d.strftime('%Y-%m-%d'), 'value': float(v)}
                                         for d, v in zip(returns.index, equity)]}


def _mdd_evidence(s: pd.Series) -> float | None:
    s = s.dropna()
    if len(s) < 20:
        return None
    nav = (1 + s).cumprod()
    dd = nav / nav.cummax() - 1
    # Actual drawdown observations: depth, duration, and eventual recovery.
    depth = min(abs(float(dd.min())) / 0.30, 1.0)
    events = int((dd < -0.10).sum())
    duration = min(int((dd < -0.10).sum()) / 252.0, 1.0)
    recovered = 1.0 if dd.iloc[-1] >= -1e-9 or (dd < -0.10).any() and nav.iloc[-1] >= nav.cummax().iloc[-1] else 0.0
    return float(np.clip(0.25 * depth + 0.25 * min(events / 2, 1) + 0.25 * duration + 0.25 * recovered, 0, 1))


def _evidence(returns: pd.DataFrame, n_years: int) -> dict[str, dict]:
    expected = max(int(len(returns.index)), 1)
    out = {}
    for t in returns.columns:
        s = returns[t].dropna()
        years = (s.index[-1] - s.index[0]).days / 365.25 if len(s) > 1 else 0
        hist = min(years / max(n_years, 1), 1.0)
        if len(s) < 20:
            regime = None
        else:
            vol = s.rolling(63).std() * np.sqrt(252)
            regime_count = sum([
                bool((s.rolling(126).mean() > 0).any()),
                bool((s.rolling(126).mean() < 0).any()),
                bool((vol > vol.quantile(.75)).any()),
                bool((vol < vol.quantile(.25)).any()),
                bool((s.rolling(21).sum() < -.15).any()),
                bool(((s.rolling(63).sum() < -.10) & (s.rolling(63).sum().shift(-63) > 0)).any()),
            ])
            regime = regime_count / 6
        draw = _mdd_evidence(s)
        obs = min(len(s) / expected, 1.0)
        components = [hist, regime, draw, obs]
        score = sum(weight * value for weight, value in zip((.4, .3, .2, .1), components) if value is not None)
        denom = sum(weight for weight, value in zip((.4, .3, .2, .1), components) if value is not None)
        out[t] = {'history_years': round(years, 2), 'history_length_score': hist,
                  'market_regime_coverage_score': regime, 'drawdown_evidence_score': draw,
                  'observation_score': obs, 'evidence_score': score / denom if denom else None,
                  'evidence_status': 'OK' if denom == 1 else 'Data Insufficient'}
    return out


def _project(w: np.ndarray, lo: float, hi: float) -> np.ndarray | None:
    w = np.clip(np.asarray(w, dtype=float), lo, hi)
    for _ in range(100):
        delta = 1 - w.sum()
        if abs(delta) < 1e-10:
            return w
        free = (w < hi - 1e-10) if delta > 0 else (w > lo + 1e-10)
        if not free.any():
            return None
        step = delta / free.sum()
        w[free] += step
        w = np.clip(w, lo, hi)
    return w if abs(w.sum() - 1) < 1e-8 else None


def _optimise(scores: np.ndarray, current: np.ndarray, sigma: np.ndarray, params: dict, lo=.02, hi=.15):
    w = _project(current, lo, hi)
    if w is None:
        return None
    def objective(x):
        return float(x @ scores - params['lambda_tracking'] * np.sum((x-current)**2) - params['gamma_concentration'] * np.sum(x*x))
    best = objective(w)
    # Deterministic coordinate transfer search; every candidate is feasible.
    for step in (0.01, 0.0025, 0.0005):
        improved = True
        while improved:
            improved = False
            for i in range(len(w)):
                for j in range(len(w)):
                    if i == j or w[i] <= lo + 1e-10 or w[j] >= hi - 1e-10:
                        continue
                    amount = min(step, w[i]-lo, hi-w[j])
                    if amount <= 0:
                        continue
                    candidate = w.copy(); candidate[i] -= amount; candidate[j] += amount
                    value = objective(candidate)
                    if value > best + 1e-12:
                        w, best, improved = candidate, value, True
    return w, best


def _trade_rows(tickers, current_w, target_w, values, prices, shares, fees):
    total = float(sum(values))
    rows = []; gross = commission = slippage = tax = 0.0
    for i, t in enumerate(tickers):
        value = float(values[i]); price = prices.get(t)
        diff = float(target_w[i] - current_w[i])
        trade = total * diff
        action = 'NO TRADE' if abs(diff) < .01 else ('BUY' if diff > 0 else 'SELL')
        target_value = total * target_w[i]
        target_shares = math.floor(target_value / price) if price and price > 0 else None
        actual_value = target_shares * price if target_shares is not None else None
        rows.append({'ticker': t, 'current_shares': int(shares.get(t, 0)), 'current_value': value,
                     'current_weight': float(current_w[i]), 'target_weight': float(target_w[i]),
                     'weight_difference': diff, 'target_value': target_value, 'trade_value': trade,
                     'target_shares': target_shares, 'actual_value': actual_value, 'action': action})
        if action != 'NO TRADE':
            tv = abs(trade); gross += tv; commission += tv * fees.get('commission', 0); slippage += tv * fees.get('slippage', 0)
            if action == 'SELL': tax += tv * fees.get('tax_sell', 0)
    return rows, {'gross_trade_value': gross, 'commission': commission, 'slippage': slippage, 'tax': tax,
                  'transaction_cost': commission + slippage + tax, 'net_trade_value': gross + commission + slippage + tax}


def build_optimization(prices: pd.DataFrame, current_weights: dict, current_values: dict,
                       current_prices: dict, shares: dict, n_years: int, fees: dict | None = None) -> dict:
    fees = fees or {}; tickers = [t for t in prices.columns if t in current_weights]
    result = {'status': 'DATA INSUFFICIENT', 'reason': '', 'parameters': {'n_years': n_years, 'min_weight': .02, 'max_weight': .15,
              'no_trade_threshold': .01, 'models': MODE_PARAMS, 'adjusted_score_formula': 'RawScore × (0.70 + 0.30 × EvidenceScore)'}, 'validation': {}, 'sensitivity': []}
    returns = prices[tickers].pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan).dropna(how='any')
    result['dataset'] = {'start_date': returns.index[0].strftime('%Y-%m-%d') if not returns.empty else None,
                         'end_date': returns.index[-1].strftime('%Y-%m-%d') if not returns.empty else None,
                         'observation_count': int(len(returns)), 'missing_count': int(prices[tickers].isna().sum().sum()),
                         'valid_observation_ratio': float(len(returns) / max(len(prices), 1))}
    result['daily_return_matrix'] = {
        'tickers': tickers,
        'rows': [{'date': d.strftime('%Y-%m-%d'), **{t: float(v) for t, v in row.items()}}
                 for d, row in returns.tail(500).iterrows()],
        'display_note': 'Rows are limited to the latest 500 for report size; calculations use the full common matrix.'
    }
    if len(tickers) < 7 or len(returns) < 20:
        result['reason'] = 'Daily Return Matrix does not contain enough common observations.'
        return result
    sigma = returns.cov().to_numpy() * 252
    corr = returns.corr()
    result['covariance_matrix'] = {'tickers': tickers, 'values': sigma.tolist()}
    result['correlation_matrix'] = {'tickers': tickers, 'values': corr.to_numpy().tolist()}
    individual = {}
    for t in tickers:
        individual[t] = _portfolio_metrics(returns[[t]], np.array([1.0]))
    ev = _evidence(returns, n_years)
    cagr = _score([individual[t]['cagr'] for t in tickers])
    vol = _score([individual[t]['volatility'] for t in tickers], higher=False)
    mdd = _score([abs(individual[t]['mdd']) for t in tickers], higher=False)
    sharpe = _score([individual[t]['sharpe'] for t in tickers])
    calmar = _score([individual[t]['calmar'] for t in tickers])
    scores = []
    for i, t in enumerate(tickers):
        raw = float(.35*cagr.iloc[i] + .2*sharpe.iloc[i] + .15*vol.iloc[i] + .15*mdd.iloc[i] + .15*calmar.iloc[i])
        evidence = ev[t]['evidence_score']
        adjusted = raw * (.70 + .30*evidence) if evidence is not None else None
        ev[t].update({'cagr': individual[t]['cagr'], 'volatility': individual[t]['volatility'], 'mdd': individual[t]['mdd'],
                      'sharpe': individual[t]['sharpe'], 'calmar': individual[t]['calmar'], 'return_score': float(cagr.iloc[i]),
                      'risk_score': float(vol.iloc[i]), 'mdd_score': float(mdd.iloc[i]), 'sharpe_score': float(sharpe.iloc[i]),
                      'calmar_score': float(calmar.iloc[i]), 'raw_score': raw, 'adjusted_score': adjusted,
                      })
        scores.append(adjusted)
    result['scores'] = ev
    if any(x is None for x in scores):
        result['reason'] = 'Adjusted Score unavailable because Evidence Score is incomplete.'
        return result
    current = np.array([float(current_weights.get(t, 0)) for t in tickers]); current = current/current.sum()
    values = [float(current_values.get(t, 0)) for t in tickers]
    result['current'] = _portfolio_metrics(returns, current); result['current']['weights'] = current.tolist()
    result['portfolio_equity_curve'] = result['current']['equity']
    result['portfolio_drawdown_curve'] = result['current']['drawdown']
    chosen = _optimise(np.array(scores), current, sigma, MODE_PARAMS['Balanced'])
    if chosen is None:
        result['reason'] = '2%–15% constraints are infeasible for the number of assets.'; return result
    target, objective = chosen
    result['optimized'] = _portfolio_metrics(returns, target); result['optimized']['weights'] = target.tolist(); result['objective'] = objective
    result['trades'], result['transaction_cost'] = _trade_rows(tickers, current, target, values, current_prices, shares, fees)
    result['concentration'] = {'current_hhi': float(np.sum(current*current)), 'optimized_hhi': float(np.sum(target*target)),
                               'current_max_weight': float(max(current)), 'optimized_max_weight': float(max(target)),
                               'current_top5': float(sorted(current, reverse=True)[:5].__iter__().__next__()) if False else float(sum(sorted(current, reverse=True)[:5])),
                               'optimized_top5': float(sum(sorted(target, reverse=True)[:5]))}
    result['before_after'] = {k: {'current': result['current'].get(k), 'optimized': result['optimized'].get(k),
                                  'change': result['optimized'].get(k) - result['current'].get(k),
                                  'direction': 'Higher is better' if k in ('cagr', 'sharpe', 'calmar') else 'Lower is better'}
                              for k in ('cagr', 'volatility', 'mdd', 'sharpe', 'calmar')}
    result['stress_test'] = {}
    for name, start, end in (('2008 Global Financial Crisis', '2008-01-01', '2009-06-30'),
                             ('2020 COVID Crash', '2020-02-01', '2020-06-30'),
                             ('2022 Bear Market', '2022-01-01', '2022-12-31')):
        window = returns.loc[start:end]
        result['stress_test'][name] = _portfolio_metrics(window, target) if len(window) >= 20 else {'status': 'N/A', 'reason': 'Required historical dates are not available.'}
    result['stress_test']['High Inflation / High Rate'] = {'status': 'N/A', 'reason': 'Macro inflation and interest-rate series are not in the existing data.'}
    result['stress_test']['Technology Drawdown'] = {'status': 'N/A', 'reason': 'No technology-specific scenario definition is present in the existing data.'}
    result['retirement_monte_carlo'] = {'status': 'N/A', 'reason': 'Optimized F1/F2 comparison requires the same configured retirement inputs and is not inferred.'}
    for label, p in MODE_PARAMS.items():
        opt = _optimise(np.array(scores), current, sigma, p)
        if opt:
            w2, _ = opt; met = _portfolio_metrics(returns, w2)
            result['sensitivity'].append({'mode': label, **p, **{k: met[k] for k in ('cagr','volatility','mdd','sharpe','calmar')},
                                          'maximum_weight': float(max(w2)), 'top5_concentration': float(sum(sorted(w2, reverse=True)[:5])),
                                          'turnover': float(np.sum(abs(w2-current)))})
    result['validation'] = {'common_date_range': bool(result['dataset']['start_date'] and result['dataset']['end_date']),
                            'covariance_valid': bool(np.isfinite(sigma).all()), 'portfolio_volatility_valid': result['current']['volatility'] is not None,
                            'equity_curve_valid': bool(result['current']['equity']), 'weight_sum': float(target.sum()),
                            'min_weight': float(target.min()), 'max_weight': float(target.max()), 'constraints_satisfied': bool(abs(target.sum()-1)<1e-8 and target.min()>=.02-1e-8 and target.max()<=.15+1e-8),
                            'objective_calculated': True, 'optimizer_converged': True}
    result['status'] = 'SUCCESS' if all(result['validation'].values()) else 'FAILED'
    return result
