"""
app.py — Flask 入口
- 4 個 API：
  GET  /                  首頁
  GET  /api/health        健康檢查
  GET  /api/profiles      列出 user_profile/*.csv
  GET  /api/profile/<n>   預覽單檔名單
  POST /api/analyze       主分析（3 模式 + N-Year 預估）
  POST /api/export        匯出 HTML
- 報表檔案透過 /data/reports/ 靜態路徑下載
"""
from __future__ import annotations

import io
import json
import sys
import math

import warnings
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
from flask import (
    Flask, jsonify, render_template, request, send_from_directory, url_for,
)
from werkzeug.utils import secure_filename

# 確保根目錄在 sys.path（讓 from lib.xxx 有效）
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Suppress pandas RuntimeWarnings (e.g., "invalid value encountered in subtract")
# from nanops.py when computing std/var on data with NaN/inf values
warnings.filterwarnings('ignore', category=RuntimeWarning, module='pandas')

# 註:Flask 3.x 已讀 DefaultJSONProvider,下面 `flask.Flask.json_encoder = ...`
# 是 no-op;真正的 JSON sanitizer 改寫在 create_app() 內的 SafeJSONProvider。
# 保留 module 註記避免下次又踩這個坑。

from app_config import (  # noqa: E402
    DATA_DIR, DEFAULT_N_YEARS, DEFAULT_PV, DEFAULT_START_DATE,
    LOGS_DIR, MAX_CONTENT_LENGTH, REPORTS_DIR, ROOT_DIR, STATIC_DIR,
    TEMPLATES_DIR, USER_PROFILE_DIR,
)
from lib.csv_loader import (  # noqa: E402
    CSVLintError, list_profile_csvs, load_portfolio_csv, normalize_profile_csv,
)
from lib.exporter import render_html_report, render_rebalance_report  # noqa: E402
from lib.finmind import FinMindClient, FinMindError, load_finmind_token  # noqa: E402
from lib.forecast import ForecastError, build_forecast  # noqa: E402
from lib.i18n import TERMS  # noqa: E402
from lib.model_validator import (  # noqa: E402  # Phase 4.1
    ModelValidationError, raise_if_critical, validate_all,
)
from lib.portfolio import (  # noqa: E402
    BacktestError, build_adjusted_close, build_benchmark, build_portfolio,
    compute_market_value, per_stock_history, per_stock_n_year_window,
    prices_to_pivot, recent_n_year_metrics,
)
from lib.risk_metrics import RiskMetricsError, run_risk_metrics  # noqa: E402
from lib.volatility_decay import VolatilityDecayError, run_volatility_decay  # noqa: E402
from lib.benchmarks import BenchmarkError, run_benchmark_compare  # noqa: E402
from lib.monte_carlo import MonteCarloConfig, MonteCarloError, simulate_monte_carlo  # noqa: E402
from lib.sequence_risk import (  # noqa: E402
    SequenceRiskConfig, SequenceRiskError, simulate_sequence_risk,
)
from lib.monthly_returns import compute_monthly_returns_by_ticker  # noqa: E402
from lib.daily_prices import (  # noqa: E402
    DailyPricesConfig, DailyPricesError, daily_prices_by_stock, portfolio_daily_returns,
)
from lib.portfolio_optimization import build_optimization  # noqa: E402


# ───────── Debug logging setup ─────────
# 三個輸出通道:
#   1. console (stdout)      - DEBUG 等級,所有人
#   2. logs/debug.log        - DEBUG 等級,所有人 (append)
#   3. logs/app.log          - ERROR+ 等級,主人用的「失敗快速看」檔
#
# 為何掛 root logger (v3.0.2 fix):
#   舊版只掛在 `portfolio_forecast` logger 上 → Flask 內建的 `app.logger`
#   (拋 "HTML 產生失敗" 的那個) 完全沒收到,Windows Flask 重啟後也看不到 traceback。
#   掛 root 後,所有子 logger (`app` / `werkzeug` / `portfolio_forecast`) 都繼承 → 都進檔。
LOG_FORMAT = '[%(asctime)s] %(levelname)s %(name)s: %(message)s'
logging.basicConfig(
    level=logging.DEBUG,
    format=LOG_FORMAT,
    datefmt='%Y-%m-%d %H:%M:%S',
)
root_logger = logging.getLogger()

LOGS_DIR.mkdir(parents=True, exist_ok=True)

# debug.log: 全部 log (DEBUG+),append
file_handler = logging.FileHandler(
    LOGS_DIR / 'debug.log',
    mode='a',
    encoding='utf-8',
)
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt='%Y-%m-%d %H:%M:%S'))
root_logger.addHandler(file_handler)

# app.log: 只收 ERROR+,主人快查「今天炸了什麼」用的
error_handler = logging.FileHandler(
    LOGS_DIR / 'app.log',
    mode='a',
    encoding='utf-8',
)
error_handler.setLevel(logging.ERROR)
error_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt='%Y-%m-%d %H:%M:%S'))
root_logger.addHandler(error_handler)

logger = logging.getLogger('portfolio_forecast')
logger.debug('=' * 60)
logger.debug('Portfolio Forecast app starting (debug log initialized)')
logger.debug(f'LOG_DIR: {LOGS_DIR}')
logger.debug(f'  debug.log: {LOGS_DIR / "debug.log"} (DEBUG+, root logger)')
logger.debug(f'  app.log:   {LOGS_DIR / "app.log"} (ERROR+, root logger)')


# ───────── Date helpers ─────────
def default_end_date(today: date | None = None) -> str:
    """回測 end_date 預設值：前一個月的最後一天 (YYYY-MM-DD)。

    設計意圖 (v3.0.2 fix):
      - 歷史回測不需要「當下」的價格,反正每月才更新一次資料
      - 同一個月內多次執行 → end_date 固定 → cache key 穩定 → 0 抓取
      - 跨月第一次執行 → end_date 推進一格 → cache miss → 補抓一個月 → merge

    Args:
        today: 注入用的「今天」(預設 = date.today()),測試用可傳任意值。
              不接受字串,傳 date 物件。

    Edge case (1 月跨年): 回 去年 12-31
    """
    if today is None:
        today = date.today()
    last_of_prev = date(today.year, today.month, 1) - timedelta(days=1)
    return last_of_prev.strftime('%Y-%m-%d')


def create_app() -> Flask:
    app = Flask(
        __name__,
        static_folder=str(STATIC_DIR),
        template_folder=str(TEMPLATES_DIR),
    )
    app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

    # Flask 3.x JSON safety:override dumps 將 NaN / ±inf 換 None。
    # 原本 `flask.Flask.json_encoder = SafeJSONEncoder` 是 Flask 2.x API,
    # Flask 3.x 讀 DefaultJSONProvider,結果 NaN 直接輸出成 `{"k":NaN}`
    # → 前端 JSON.parse 崩(2026-08-27 慘案)。
    from flask.json.provider import DefaultJSONProvider

    def _scrub_nan(obj):
        """遞歸把 float NaN / ±inf 換成 None;list / dict 走訪子節點"""
        if isinstance(obj, float):
            if math.isnan(obj) or math.isinf(obj):
                return None
            return obj
        if isinstance(obj, dict):
            return {k: _scrub_nan(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            cleaned = [_scrub_nan(v) for v in obj]
            return type(obj)(cleaned) if isinstance(obj, tuple) else cleaned
        return obj

    class SafeJSONProvider(DefaultJSONProvider):
        def dumps(self, obj, **kwargs):
            return super().dumps(_scrub_nan(obj), **kwargs)

    app.json = SafeJSONProvider(app)
    # 開發/部署友善：templates 改完不需 restart Flask。
    # 背景：2026-08-26 B6 commit 後 Windows 主機那個 Flask 進程(Python 3.13.1,啟動早於 B6 push)
    #       仍跑舊版 index.html,master reload 看不到 ⑨⑩ 卡片。template 在 process memory 緩存,
    #       debug=False 時 use_reloader=False 不會自動重載。開啟 TEMPLATES_AUTO_RELOAD 後
    #       下次 request 會讀新檔。對應 ticket: 2026-08-25-retirement-decision-v2-fresh §3
    app.config['TEMPLATES_AUTO_RELOAD'] = True

    # ────────────── 頁面 ──────────────
    @app.route('/')
    def index():
        return render_template(
            'index.html',
            terms_json=json.dumps(TERMS, ensure_ascii=False),
        )

    @app.route('/data/reports/<path:filename>')
    def serve_report(filename):
        return send_from_directory(str(REPORTS_DIR), filename, as_attachment=False)

    @app.route('/api/v2/monthly_returns', methods=['POST'])
    def api_v2_monthly_returns():
        """v3.0.3 N8: 計算每個 ticker 的逐月逐年報酬表(card ⑥)。
        Body: { "profile": "<name>" }
        Returns: { "tickers": [{"ticker": "0050", "first_year": ..., "last_year": ..., "data": {...}}] }
        """
        body = request.get_json(silent=True) or {}
        profile = (body.get('profile') or '').strip()
        if not profile:
            raise _BadInput('profile 必填')
        if '/' in profile or '\\' in profile or '..' in profile:
            raise _BadInput('profile 名稱不合法')
        profile_path = USER_PROFILE_DIR / f'{profile}.csv'
        if not profile_path.is_file():
            raise _BadInput(f'{profile}.csv 不存在')

        holdings = load_portfolio_csv(profile_path)
        tickers = [h.ticker for h in holdings]
        if not tickers:
            raise _BadInput('profile 無 holdings')

        # v3.0.4 P0 fix: 逐 ticker 獨立抓 + 走 fresh-start-per-month shares tracking
        # (不走 daily returns 路線,避免 cumulative adj + pct_change 被 shares 稀釋)
        # 沒 div/split cache 的 ticker 自動 fallback 到 raw close(等同舊行為)
        from lib.monthly_returns import compute_monthly_returns_via_shares_tracking  # noqa
        from lib.portfolio import prices_to_pivot  # noqa

        finmind = FinMindClient()
        end_date = default_end_date()
        rows_by_ticker: dict[str, list] = {}
        dividends_by_ticker: dict[str, list] = {}
        splits_by_ticker: dict[str, list] = {}
        for ticker in tickers:
            try:
                rows = finmind.get_stock_price(ticker, '2014-01-01', end_date, use_cache=True)
            except Exception:
                continue
            if not rows:
                continue
            rows_by_ticker[ticker] = rows
            try:
                dividends_by_ticker[ticker] = finmind.get_dividends(ticker, '2014-01-01', end_date)
            except Exception:
                dividends_by_ticker[ticker] = []
            try:
                splits_by_ticker[ticker] = finmind.get_splits(ticker, '2014-01-01', end_date)
            except Exception:
                splits_by_ticker[ticker] = []
        if not rows_by_ticker:
            return jsonify({'tickers': []})

        prices = prices_to_pivot(rows_by_ticker, price_col='close')
        out = compute_monthly_returns_via_shares_tracking(
            prices,
            dividends_by_ticker=dividends_by_ticker,
            splits_by_ticker=splits_by_ticker,
        )
        return jsonify(out)

    @app.route('/favicon.ico')
    def favicon():
        # 避免 404 noise:用 1×1 透明 PNG(不是 ICO 但能跨瀏覽器避免報錯)
        from flask import Response
        return Response(
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
            b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xff'
            b'\xff?\x00\x05\xfe\x02\xfe\xdc\xcc\x59\xe7\x00\x00\x00\x00IEND\xaeB`\x82',
            mimetype='image/png',
        )

    # ────────────── 健康檢查 ──────────────
    @app.get('/api/health')
    def health():
        checks = {
            'finmind_token': bool(load_finmind_token()),
            'user_profile_dir': USER_PROFILE_DIR.is_dir(),
            'profile_csvs': list_profile_csvs(USER_PROFILE_DIR),
            'python_ok': True,
        }
        try:
            import pandas  # noqa: F401
            checks['pandas_ok'] = True
        except ImportError:
            checks['pandas_ok'] = False
        all_ok = all(v for v in checks.values() if isinstance(v, bool))
        return jsonify({'ok': all_ok, 'checks': checks}), 200 if all_ok else 503

    # ────────────── 名單 ──────────────
    @app.get('/api/profiles')
    def profiles():
        return jsonify({
            'profiles': list_profile_csvs(USER_PROFILE_DIR),
            'dir': str(USER_PROFILE_DIR),
        })

    @app.get('/api/profile/<name>')
    def profile_preview(name: str):
        # 防止 path traversal
        if '/' in name or '\\' in name or '..' in name:
            return jsonify({'error': 'invalid name'}), 400
        path = USER_PROFILE_DIR / f'{name}.csv'
        if not path.is_file():
            return jsonify({'error': f'{name}.csv not found'}), 404
        try:
            holdings = load_portfolio_csv(path)
        except CSVLintError as e:
            return jsonify({'error': str(e)}), 400
        return jsonify({
            'name': name,
            'count': len(holdings),
            'holdings': [{'ticker': h.ticker, 'shares': h.shares} for h in holdings],
        })

    # ────────────── 上傳名單 CSV ──────────────
    @app.post('/api/upload_profile')
    def upload_profile():
        """瀏覽器上傳 CSV → 存到 user_profile/ → 驗格式。
        用 werkzeug.utils.secure_filename 防 path traversal；
        用既有 load_portfolio_csv 做內容驗證（壞檔不落地）。

        v3.0.3:加 normalize gate。流程：
          1. 先用既有 parser 驗格式(壞檔 400,不落地)
          2. 寫到 tmp 檔,跑 normalize_profile_csv
          3. 若任一 ticker 對不上 → 400 + TICKER_NOT_FOUND + failed 清單(tmp 不落地)
          4. 若 normalize 成功(有改 / 無改都可)→ atomic rename 到正式位置
        """
        if 'file' not in request.files:
            return jsonify({'error': '沒有收到檔案'}), 400
        f = request.files['file']
        if not f.filename:
            return jsonify({'error': '檔名是空的'}), 400
        safe = secure_filename(f.filename)
        if not safe or not safe.lower().endswith('.csv'):
            return jsonify({'error': '只接受 .csv 檔案'}), 400
        name = safe[:-4]  # strip .csv
        if not name:
            return jsonify({'error': '檔名不可為空'}), 400
        try:
            content = f.read().decode('utf-8-sig')
        except UnicodeDecodeError as e:
            return jsonify({'error': f'編碼錯誤（需 UTF-8）：{e}'}), 400
        try:
            load_portfolio_csv(io.StringIO(content))
        except CSVLintError as e:
            return jsonify({'error': f'CSV 格式錯誤：{e}'}), 400

        # v3.0.3 normalize gate
        out = USER_PROFILE_DIR / f'{name}.csv'
        tmp = out.with_suffix(out.suffix + '.incoming.tmp')
        try:
            tmp.write_bytes(content.encode('utf-8-sig'))
            result = normalize_profile_csv(tmp)
            if result.failed:
                tmp.unlink(missing_ok=True)
                return jsonify({
                    'error': f'CSV 有 {len(result.failed)} 個代號無法辨識',
                    'code': 'TICKER_NOT_FOUND',
                    'failed': result.failed,
                }), 400
            tmp.replace(out)
            return jsonify({
                'name': name,
                'file': safe,
                'size': out.stat().st_size,
                'normalized': result.applied,
                'changes': result.changes,
            }), 200
        except CSVLintError as e:
            tmp.unlink(missing_ok=True)
            return jsonify({'error': f'CSV 格式錯誤：{e}'}), 400
        except Exception:
            tmp.unlink(missing_ok=True)
            raise

    # ────────────── 主分析 ──────────────
    @app.post('/api/analyze')
    def analyze():
        body = request.get_json(silent=True) or {}
        logger.debug(f'POST /api/analyze received: profile={body.get("profile")}, n={body.get("n")}')
        try:
            result = _run_analyze(body)
            logger.debug(f'POST /api/analyze success: keys={list(result.keys())}')
            # Sanity check:若上游漏 NaN/inf,allow_nan=False 會 raise → 被下面 except 接住 500。
            # 正確的清理由 app.json(SafeJSONProvider.dumps)執行,response 仍是合法 JSON。
            try:
                json.dumps(result, ensure_ascii=False, allow_nan=False)
            except ValueError:
                logger.error(f'POST /api/analyze: NaN/Inf leaked into result')
        except _BadInput as e:
            logger.warning(f'POST /api/analyze: BadInput - {e}')
            return _bad_input_response(e)
        except (CSVLintError, BacktestError, ForecastError, FinMindError) as e:
            logger.warning(f'POST /api/analyze: {type(e).__name__} - {e}')
            return jsonify({'error': str(e)}), 400
        except Exception as e:  # noqa: BLE001
            logger.error(f'POST /api/analyze: Internal error - {type(e).__name__}: {e}', exc_info=True)
            return jsonify({'error': f'內部錯誤：{type(e).__name__}: {e}'}), 500
        return jsonify(result)

    # ────────────── 匯出 ──────────────
    @app.post('/api/export')
    def export():
        body = request.get_json(silent=True) or {}
        result = body.get('result')
        fmt = (body.get('format') or 'html').lower()
        profile_name = (body.get('profile_name') or '').strip()
        report_type = (body.get('report_type') or 'forecast').lower()
        if not result or not isinstance(result, dict):
            return jsonify({'error': 'result 不可為空'}), 400
        if fmt != 'html':
            return jsonify({'error': 'format 必須是 html'}), 400

        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        if report_type not in ('forecast', 'rebalance'):
            return jsonify({'error': 'report_type 必須是 forecast 或 rebalance'}), 400
        # profile_name may arrive as either "kadela" or "kadela.csv".
        # Keep only a safe filename stem and make the report identifiable.
        profile_stem = Path(secure_filename(profile_name)).stem if profile_name else ''
        prefix = f'{profile_stem}_' if profile_stem else ''
        fname = f'{prefix}portfolio_{"rebalance" if report_type == "rebalance" else "forecast"}_{ts}.html'
        out = REPORTS_DIR / fname
        try:
            out.write_text(
                (render_rebalance_report(result, profile_name=profile_name)
                 if report_type == 'rebalance'
                 else render_html_report(result, profile_name=profile_name)),
                encoding='utf-8',
            )
        except Exception as e:  # noqa: BLE001
            import traceback
            app.logger.error('HTML 產生失敗：%s\n%s', e, traceback.format_exc())
            return jsonify({'error': f'HTML 產生失敗：{e}'}), 500

        return jsonify({
            'file': fname,
            'url': url_for('serve_report', filename=fname),
            'format': fmt,
            'size': out.stat().st_size,
        })

    # ────────────── v2 endpoints (SPEC §4) ──────────────
    @app.get('/api/v2/health')
    def v2_health():
        """v2 健康檢查:檢查 F1-F6 依賴"""
        checks = {
            'v1_healthy': True,
            'monte_carlo': _check_import('lib.monte_carlo'),
            'sequence_risk': _check_import('lib.sequence_risk'),
            'risk_metrics': _check_import('lib.risk_metrics'),
            'volatility_decay': _check_import('lib.volatility_decay'),
            'benchmarks': _check_import('lib.benchmarks'),
            'finmind_token': bool(load_finmind_token()),
            'profile_csvs': list_profile_csvs(USER_PROFILE_DIR),
        }
        all_ok = all(v for v in checks.values() if isinstance(v, bool))
        return jsonify({
            'ok': all_ok,
            'version': 'v2',
            'features': ['F1', 'F2', 'F3', 'F4', 'F5', 'F6'],
            'checks': checks,
        }), 200 if all_ok else 503

    @app.post('/api/v2/monte_carlo')
    def v2_monte_carlo():
        """F1: Monte Carlo 10,000 次模擬"""
        body = request.get_json(silent=True) or {}
        profile = (body.get('profile') or '').strip()
        if not profile:
            return jsonify({'error': 'profile 必填'}), 400
        try:
            daily_returns, _meta = _get_profile_daily_returns(profile)
            try:
                config = MonteCarloConfig(
                    initial_balance=float(body.get('initial_balance', 7_236_096)),
                    horizon_years=int(body.get('horizon_years', 30)),
                    n_simulations=int(body.get('n_simulations', 10_000)),
                    annual_withdrawal=float(body.get('annual_withdrawal', 0.0)),
                    withdrawal_inflation=float(body.get('withdrawal_inflation', 0.03)),
                    rebalance=body.get('rebalance', 'buy_and_hold'),
                    block_bootstrap=bool(body.get('block_bootstrap', True)),
                    block_size_days=int(body.get('block_size_days', 21)),
                    seed=body.get('seed'),
                )
            except (TypeError, ValueError) as e:
                raise MonteCarloError(f'config 解析失敗:{e}') from e
            result = simulate_monte_carlo(daily_returns, config)
            return jsonify(result.to_dict())
        except _BadInput as e:
            return _bad_input_response(e)
        except MonteCarloError as e:
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            logger.error(f'/api/v2/monte_carlo error: {e}', exc_info=True)
            return jsonify({'error': f'內部錯誤:{type(e).__name__}: {e}'}), 500

    @app.post('/api/v2/sequence_risk')
    def v2_sequence_risk():
        """F2: 退休提款存活率(包 F1 引擎 + 通膨提款)"""
        body = request.get_json(silent=True) or {}
        profile = (body.get('profile') or '').strip()
        if not profile:
            return jsonify({'error': 'profile 必填'}), 400
        try:
            daily_returns, _meta = _get_profile_daily_returns(profile)
            monthly = float(body.get('withdrawal_monthly', 30_000))
            try:
                config = SequenceRiskConfig(
                    initial_balance=float(body.get('initial_balance', 7_236_096)),
                    horizon_years=int(body.get('horizon_years', 30)),
                    n_simulations=int(body.get('n_simulations', 10_000)),
                    retirement_age=int(body.get('retirement_age', 60)),
                    current_age=int(body.get('current_age', body.get('retirement_age', 60))),
                    retirement_end_age=body.get('retirement_end_age'),
                    withdrawal_monthly=monthly,
                    withdrawal_inflation=float(body.get('withdrawal_inflation', 0.03)),
                    pension_monthly=float(body.get('pension_monthly', 0.0)),
                    pension_inflation=float(body.get('pension_inflation', 0.02)),
                    pension_start_age=body.get('pension_start_age'),
                    special_expenses=body.get('special_expenses') or [],
                    block_bootstrap=bool(body.get('block_bootstrap', True)),
                    block_size_days=int(body.get('block_size_days', 21)),
                    seed=body.get('seed'),
                )
            except (TypeError, ValueError) as e:
                raise SequenceRiskError(f'config 解析失敗:{e}') from e
            result = simulate_sequence_risk(daily_returns, config)
            return jsonify(result.to_dict())
        except _BadInput as e:
            return _bad_input_response(e)
        except SequenceRiskError as e:
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            logger.error(f'/api/v2/sequence_risk error: {e}', exc_info=True)
            return jsonify({'error': f'內部錯誤:{type(e).__name__}: {e}'}), 500

    @app.post('/api/v2/risk_metrics')
    def v2_risk_metrics():
        """F3 + F6: VaR/CVaR + Sharpe with Rf"""
        body = request.get_json(silent=True) or {}
        profile = (body.get('profile') or '').strip()
        if not profile:
            return jsonify({'error': 'profile 必填'}), 400
        try:
            daily_returns, _meta = _get_profile_daily_returns(profile)
            result = run_risk_metrics(daily_returns, body)
            return jsonify(result)
        except _BadInput as e:
            return _bad_input_response(e)
        except RiskMetricsError as e:
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            logger.error(f'/api/v2/risk_metrics error: {e}', exc_info=True)
            return jsonify({'error': f'內部錯誤:{type(e).__name__}: {e}'}), 500

    @app.post('/api/v2/volatility_decay')
    def v2_volatility_decay():
        """F4: 0050 vs 00631L 波動耗損"""
        body = request.get_json(silent=True) or {}
        try:
            client = FinMindClient()
            u_id = body.get('ticker_underlying', '0050')
            l_id = body.get('ticker_leveraged', '00631L')
            start = body.get('initial_date', '2014-10-31')
            end_date = default_end_date()
            try:
                u_rows = client.get_stock_price(u_id, start, end_date, use_cache=True)
            except FinMindError as e:
                return jsonify({'error': f'{u_id} 抓取失敗:{e}'}), 400
            if not u_rows:
                return jsonify({'error': f'{u_id} 無報價資料(start={start})'}), 400
            try:
                l_rows = client.get_stock_price(l_id, start, end_date, use_cache=True)
            except FinMindError as e:
                return jsonify({'error': f'{l_id} 抓取失敗:{e}'}), 400
            if not l_rows:
                return jsonify({'error': f'{l_id} 無報價資料(start={start})'}), 400
            u_prices = prices_to_pivot({u_id: u_rows}, price_col='close')[u_id]
            l_prices = prices_to_pivot({l_id: l_rows}, price_col='close')[l_id]
            result = run_volatility_decay(u_prices, l_prices, body)
            return jsonify(result)
        except VolatilityDecayError as e:
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            logger.error(f'/api/v2/volatility_decay error: {e}', exc_info=True)
            return jsonify({'error': f'內部錯誤:{type(e).__name__}: {e}'}), 500

    @app.post('/api/v2/benchmark_compare')
    def v2_benchmark_compare():
        """F5: 多基準比較 (0050 + 006208) — 兩個市值型 ETF 作為大盤代理"""
        body = request.get_json(silent=True) or {}
        profile = (body.get('profile') or '').strip()
        benchmarks = body.get('benchmarks', ['0050', '006208'])
        if not profile:
            return jsonify({'error': 'profile 必填'}), 400
        try:
            nav, _meta = _get_profile_nav(profile)
            client = FinMindClient()
            benchmark_prices: dict = {}
            skipped: list = []
            for ticker in benchmarks:
                try:
                    rows = client.get_stock_price(
                        ticker,
                        body.get('start_date', DEFAULT_START_DATE),
                        default_end_date(),
                    )
                    prices = prices_to_pivot({ticker: rows}, price_col='close')
                    if ticker in prices.columns:
                        benchmark_prices[ticker] = prices[ticker]
                except FinMindError as e:
                    skipped.append(f'{ticker}: {e}')
            result = run_benchmark_compare(nav, benchmark_prices, body)
            result['fetch_skipped'] = skipped
            return jsonify(result)
        except BenchmarkError as e:
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            logger.error(f'/api/v2/benchmark_compare error: {e}', exc_info=True)
            return jsonify({'error': f'內部錯誤:{type(e).__name__}: {e}'}), 500

    # ────────────── 錯誤 ──────────────
    @app.errorhandler(404)
    def not_found(_e):
        if request.path.startswith('/api/'):
            return jsonify({'error': 'not found'}), 404
        return jsonify({'error': 'not found'}), 404

    @app.errorhandler(500)
    def server_error(e):
        return jsonify({'error': str(e)}), 500

    return app


# ────────────── 核心邏輯 ──────────────
class _BadInput(ValueError):
    """v3.0.3: 可攜帶結構化 payload (code / failed / changes 等),
    讓前端 detail panel 能讀細節,不只看 error 字串。
    """
    def __init__(self, message: str, *, code: str | None = None, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


def _bad_input_response(e: _BadInput):
    """v3.0.3: 把 _BadInput 轉成 JSON response。
    若有 code / details,一起帶出來給前端 detail panel 用。
    """
    payload: dict = {'error': str(e)}
    if e.code:
        payload['code'] = e.code
    payload.update(e.details)
    return jsonify(payload), 400


def _check_import(module_path: str) -> bool:
    """檢查模組是否可以 import(v2 health check 用)"""
    try:
        __import__(module_path)
        return True
    except Exception:  # noqa: BLE001
        return False


def _fetch_daily_portfolio_returns(
    profile: str,
    client: FinMindClient | None = None,
) -> tuple[pd.Series, dict]:
    """從 holdings CSV 取 **daily** portfolio return(修股寶 reject bug)

    Bug 股寶 20:19 reject 指出的核心問題：
    - 舊 _get_profile_daily_returns 拿 _run_analyze() 的 NAV
    - NAV 點數 ~515 點/12.6y = 月 K(不是日 K)
    - 把月變化當日變化複利 5040 次,所有 F1/F2/F3/F6 數字膨脹 12 倍

    修法(A 法,股寶推薦):
    1. 取 holdings: list[Holding(ticker, shares)]
    2. 每個 ticker 走 FinMind TaiwanStockPrice 拿 daily close
    3. 對齊到所有 ticker 共同交易日(common intersection)
    4. pct_change on (date × ticker) close table → daily returns per ticker
    5. 用「第一天 close × shares」算初始市值 → weights
    6. portfolio_daily_return = sum(weight_i × return_i)
    7. 回傳 pd.Series(以日期為 index)

    Args:
        profile: profile 名稱(對應 user_profile/{profile}.csv)
        client: 可注入的 FinMindClient 實例(測試用 mock)

    Returns:
        (daily_returns Series, meta dict)
    """
    profile_path = USER_PROFILE_DIR / f'{profile}.csv'
    if not profile_path.is_file():
        raise _BadInput(f'{profile}.csv 不存在')

    # v3.0.3 normalize gate（冪等）
    # CSV 進來時已經是 canonical(由 /api/upload_profile 寫入),這裡主要擋直接
    # 塞檔到 user_profile/ 又跑 analyze 的攻擊面 + 舊檔未 normalized 的情境。
    # 成功 applied=False 代表冪等,applied=True 寫回後繼續。
    try:
        norm_result = normalize_profile_csv(profile_path)
    except CSVLintError as ce:
        raise _BadInput(f'CSV 格式錯誤:{ce}')
    if norm_result.failed:
        raise _BadInput(
            f'profile {profile!r} 的 CSV 有 {len(norm_result.failed)} 個代號無法辨識',
            code='TICKER_NOT_FOUND',
            details={'failed': norm_result.failed, 'profile': profile},
        )

    holdings = load_portfolio_csv(profile_path)
    if not holdings:
        raise _BadInput('名單為空')

    if client is None:
        client = FinMindClient()

    today = default_end_date()  # 改用「前一個月最後一天」,cache 才不會每天 miss

    # A 法（股寶推薦）：用 lib.daily_prices 拿 (date × symbol) close,
    # 避免舊 _run_analyze 的 NAV 是月 K 被當日 K 複利 12 倍
    try:
        prices_config = DailyPricesConfig(
            start_date=DEFAULT_START_DATE,
            end_date=today,
            use_cache=True,
        )
        close_df = daily_prices_by_stock(
            client,
            [h.ticker for h in holdings],
            prices_config,
        )
    except DailyPricesError as e:
        raise _BadInput(f'daily prices 取得失敗:{e}') from e

    if len(close_df) < 30:
        raise _BadInput(
            f'對齊後歷史太短({len(close_df)} 天),至少需 30 個交易日'
        )

    # weights = 第一個交易日 close × shares
    first_close = close_df.iloc[0]
    shares_series = pd.Series({h.ticker: h.shares for h in holdings})
    market_values = first_close * shares_series
    total_mv = float(market_values.sum())
    if total_mv <= 0:
        raise _BadInput(f'初始市值 <= 0:{market_values.to_dict()}')
    weights = market_values / total_mv

    # 加權 portfolio daily return（走 lib.daily_prices helper）
    portfolio_returns = portfolio_daily_returns(
        close_df,
        weights.to_dict(),
    )
    portfolio_returns.name = 'portfolio'

    # v3.0.4 P0 fix: 逐 ticker 算 daily returns(card ⑥ 月報表用)
    # 走 fresh-start-per-month shares tracking(不被 cumulative shares 稀釋)
    # 沒 div/split cache 的 ticker 自動 fallback(等同 raw close 行為)
    from lib.monthly_returns import compute_monthly_returns_via_shares_tracking
    from lib.portfolio import prices_to_pivot

    rows_by_ticker: dict[str, list] = {}
    divs_by_ticker: dict[str, list] = {}
    splits_by_ticker: dict[str, list] = {}
    for h in holdings:
        try:
            rows = client.get_stock_price(h.ticker, DEFAULT_START_DATE, today, use_cache=True)
        except Exception:
            continue
        if not rows:
            continue
        rows_by_ticker[h.ticker] = rows
        try:
            divs_by_ticker[h.ticker] = client.get_dividends(h.ticker, DEFAULT_START_DATE, today)
        except Exception:
            divs_by_ticker[h.ticker] = []
        try:
            splits_by_ticker[h.ticker] = client.get_splits(h.ticker, DEFAULT_START_DATE, today)
        except Exception:
            splits_by_ticker[h.ticker] = []

    if rows_by_ticker:
        prices_pivot = prices_to_pivot(rows_by_ticker, price_col='close')
        monthly_out = compute_monthly_returns_via_shares_tracking(
            prices_pivot,
            dividends_by_ticker=divs_by_ticker,
            splits_by_ticker=splits_by_ticker,
        )
        # v3.0.4 P0 fix: monthly_tickers 由 _run_analyze 從 _build_analyze_meta 拿
        # (這裡只回傳 daily portfolio returns,不再順便算 monthly,避免破壞函數職責)

    # daily_returns_by_ticker 仍用 cumulative adj(給 card ⑤ / dashboard JSON 用)
    daily_returns_by_ticker: dict[str, list] = {}
    for h in holdings:
        rets, _fallback = _adj_close_daily_returns(
            h.ticker, client, DEFAULT_START_DATE, today,
        )
        if rets is None or len(rets) == 0:
            continue
        daily_returns_by_ticker[h.ticker] = [
            {'date': d.strftime('%Y-%m-%d'), 'ret': float(r)}
            for d, r in rets.items()
        ]

    meta = {
        'profile': profile,
        'holdings': len(holdings),
        'tickers': [h.ticker for h in holdings],
        'weights': {t: round(float(w), 6) for t, w in weights.items()},
        'start': str(portfolio_returns.index[0].date()),
        'end': str(portfolio_returns.index[-1].date()),
        'days': len(portfolio_returns),
        'first_market_values': {
            t: round(float(v), 0) for t, v in market_values.items()
        },
        # v3.0.3 N8: card ⑥ 用的 per-ticker daily returns
        'daily_returns_by_ticker': daily_returns_by_ticker,
    }
    return portfolio_returns, meta


def _get_profile_daily_returns(profile: str) -> tuple[pd.Series, dict]:
    """Load profile + 取 portfolio 整體的日報酬(走 FinMind daily 股價加權)
    詳見 _fetch_daily_portfolio_returns。
    """
    rets, meta = _fetch_daily_portfolio_returns(profile)
    return rets, meta









def _get_profile_nav(profile: str) -> tuple[pd.Series, dict]:
    """Load profile + 取 portfolio 的 NAV(從 daily returns 累積重建)"""
    rets, meta = _fetch_daily_portfolio_returns(profile)
    nav = (1.0 + rets).cumprod()
    nav.name = 'nav'
    return nav, meta


def _parse_weights(raw, tickers: list[str]) -> dict[str, float] | None:
    """支援 '2330:0.3,2317:0.7' 字串 或 {ticker: weight} dict"""
    if raw is None or raw == '':
        return None
    if isinstance(raw, dict):
        return {str(k).strip(): float(v) for k, v in raw.items()}
    if isinstance(raw, str):
        out: dict[str, float] = {}
        for chunk in raw.split(','):
            chunk = chunk.strip()
            if not chunk or ':' not in chunk:
                continue
            k, v = chunk.split(':', 1)
            out[k.strip()] = float(v.strip())
        return out if out else None
    raise _BadInput('weights 格式錯誤（需 dict 或 "TICKER:weight,..." 字串）')


def _run_analyze(body: dict) -> dict:
    """主分析流程：
    1) 讀名單 → FinMind TaiwanStockInfo 預先驗證 stock_id 存在 → 過濾假代號
    2) 抓 first_trading_day + 標記歷史太短的股票
    3) 抓 FinMind TaiwanStockPrice（只抓驗證過的）
    4) 三模式回測
    5) 計算起始市值（最後收盤價 × 股數）
    6) N-Year 預估
    7) 組裝回傳（含 bias 警告）
    """
    # 1) 解析輸入
    profile = (body.get('profile') or '').strip()
    if not profile:
        raise _BadInput('profile 必填（從 /api/profiles 選一個）')
    if '/' in profile or '\\' in profile or '..' in profile:
        raise _BadInput('profile 名稱不合法')
    profile_path = USER_PROFILE_DIR / f'{profile}.csv'
    if not profile_path.is_file():
        raise _BadInput(f'{profile}.csv 不存在')

    # v3.0.3 normalize gate（v1 路徑也要走,讓 /api/analyze 在 CSV 有問題時
    # 直接回 TICKER_NOT_FOUND,不落到下面重複的 user_tickers 驗證)
    try:
        norm_result = normalize_profile_csv(profile_path)
    except CSVLintError as ce:
        raise _BadInput(f'CSV 格式錯誤:{ce}')
    if norm_result.failed:
        raise _BadInput(
            f'profile {profile!r} 的 CSV 有 {len(norm_result.failed)} 個代號無法辨識',
            code='TICKER_NOT_FOUND',
            details={'failed': norm_result.failed, 'profile': profile},
        )

    holdings = load_portfolio_csv(profile_path)
    user_tickers = [h.ticker for h in holdings]
    shares_map = {h.ticker: h.shares for h in holdings}

    n = int(body.get('n', DEFAULT_N_YEARS))
    if n < 1 or n > 50:
        raise _BadInput('n 必須在 1~50 之間')
    user_pv = body.get('pv')  # None = 自動用實際市值
    start_date = (body.get('start_date') or DEFAULT_START_DATE).strip()
    end_date = (body.get('end_date') or default_end_date()).strip()
    weights = _parse_weights(body.get('weights'), user_tickers)

    # 1.5) 交易成本（選填，預設 0 = 不計）
    # Buy & hold 場景下，成本只作用在「初始買入」一次：
    #   effective_pv = pv / (1 + fee_buy + slippage)
    # 月/季 rebalancing 場景下則每次都抽。详細見 README。
    fee_buy = float(body.get('fee_buy', 0) or 0)
    fee_sell = float(body.get('fee_sell', 0) or 0)
    tax_sell = float(body.get('tax_sell', 0) or 0)
    slippage = float(body.get('slippage', 0) or 0)
    if any(x < 0 or x > 0.1 for x in (fee_buy, fee_sell, tax_sell, slippage)):
        raise _BadInput('fee/tax/slippage 應在 0~0.1（10%）之間')

    # 1.6) Benchmark（選填）
    benchmark_id = (body.get('benchmark') or '').strip() or None

    # 2) 預先驗證：TaiwanStockInfo 抓清單 → match user ticker → 過濾假代號
    client = FinMindClient()
    try:
        stock_list = client.get_stock_list()
    except FinMindError as e:
        raise _BadInput(f'FinMind TaiwanStockInfo 抓取失敗：{e}') from e

    matched: dict[str, dict] = {}        # stock_id → match 結果（含 stock_name）
    invalid_tickers: list[dict] = []     # [{user_input, reason}]
    for ut in user_tickers:
        m = client.match_ticker(ut)
        if m is None:
            invalid_tickers.append({
                'user_input': ut,
                'reason': f'在 TaiwanStockInfo 清單中查無此代號（可能是 typo 或已下市）',
            })
            continue
        sid = m['stock_id']
        if sid in matched:
            # 同一檔被多個 user ticker match 到 → 累加股數
            matched[sid]['matched_from'].append(ut)
            continue
        matched[sid] = {
            'stock_id': sid,
            'stock_name': m.get('stock_name', ''),
            'industry_category': m.get('industry_category', ''),
            'type': m.get('type', ''),
            'source': m.get('source', ''),
            'matched_from': [ut],
        }

    if not matched:
        raise _BadInput(
            '名單中所有 ticker 都不在 FinMind TaiwanStockInfo 清單內。'
            '請檢查代號是否正確（例如 50 → 0050、6208 → 006208）。'
        )

    # 3) 抓 first_trading_day + 標記歷史太短
    valid_stock_ids = list(matched.keys())
    first_trading_days: dict[str, str | None] = {}
    short_history: list[str] = []   # < N 年的 ticker
    today_ts = pd.Timestamp(end_date)
    n_years_ago = today_ts - pd.DateOffset(years=n)

    for sid in valid_stock_ids:
        try:
            ftd = client.get_first_trading_day(sid)
        except FinMindError:
            ftd = None
        first_trading_days[sid] = ftd
        if ftd is None:
            # 該股根本沒歷史股價
            invalid_tickers.append({
                'user_input': matched[sid]['matched_from'][0],
                'stock_id': sid,
                'reason': f'{sid}（{matched[sid].get("stock_name", "")}）查無任何歷史股價資料',
            })
            del matched[sid]
        else:
            ftd_ts = pd.Timestamp(ftd)
            if ftd_ts > n_years_ago:
                short_history.append(sid)

    if not matched:
        raise _BadInput('過濾掉無歷史資料的 ticker 後，沒有任何可用股票。請檢查名單。')

    # 4) 抓歷史價格（只抓驗證過 + 有 first_trading_day 的）
    final_stock_ids = list(matched.keys())
    rows_by_ticker: dict[str, list[dict]] = {}
    fetch_errors: dict[str, str] = {}
    for sid in final_stock_ids:
        try:
            # 起點用 first_trading_day 避免浪費 API 額度
            ftd = first_trading_days.get(sid, start_date)
            actual_start = max(ftd, start_date) if ftd else start_date
            rows_by_ticker[sid] = client.get_stock_price(sid, actual_start, end_date)
        except FinMindError as e:
            fetch_errors[sid] = str(e)
    # 過濾空 list
    for sid in list(rows_by_ticker.keys()):
        if not rows_by_ticker[sid]:
            del rows_by_ticker[sid]

    if not rows_by_ticker:
        raise FinMindError(f'驗證後的股票都抓不到歷史價格：{fetch_errors}')

    # 5) 轉 pivot (raw close) → 扣除 sentinel
    prices = prices_to_pivot(rows_by_ticker, price_col='close')
    if prices.empty:
        raise BacktestError('抓回的價格資料為空')

    # 5.5) 抓股息 → 產生「還原除權息後股價」（含息再投入）
    # 以「該股改 raw_pivot 中第一個有資料日期 到今天」為範圍，避免請求面被重規設為早或空取息
    dividends_by_ticker: dict[str, list[dict]] = {}
    splits_by_ticker: dict[str, list[dict]] = {}
    div_fetch_errors: dict[str, str] = {}
    for sid in final_stock_ids:
        if sid not in rows_by_ticker:
            continue
        try:
            raw_rows = rows_by_ticker[sid]
            if not raw_rows:
                continue
            actual_start = min(r['date'] for r in raw_rows)
            divs = client.get_dividends(sid, actual_start, end_date)
            splits = client.get_splits(sid, actual_start, end_date)
            dividends_by_ticker[sid] = divs
            splits_by_ticker[sid] = splits
        except Exception as e:
            div_fetch_errors[sid] = str(e)
            dividends_by_ticker[sid] = []
            splits_by_ticker[sid] = []

    prices_adj = build_adjusted_close(prices, dividends_by_ticker, splits_by_ticker)

    # 6) 起始市值（用最後一個共同交易日的收盤價 × 股數）
    # 累加同 stock_id 的股數
    combined_shares: dict[str, int] = {}
    for sid, info in matched.items():
        for ut in info['matched_from']:
            combined_shares[sid] = combined_shares.get(sid, 0) + shares_map[ut]

    mv = compute_market_value(prices, combined_shares)  # 市值 = raw close × 股數（手頭上實際市值）
    if user_pv is None:
        raw_pv = mv['total']
        pv_source = 'market_value'
    else:
        raw_pv = float(user_pv)
        pv_source = 'user_input'
        if raw_pv < 0:
            raise _BadInput('pv 不可為負')

    # 套用交易成本（Buy & hold：只在初始買入抽）
    # 驗收標準 #9：inputs.pv 跟 market_value.total 差額 < 1 元
    # 這表示 inputs.pv 就是 market_value.total（不抽費）
    # 成本只在 forecast.scenarios 套用（抽費後算 FV）
    initial_cost_rate = fee_buy + slippage
    if initial_cost_rate > 0 and pv_source == 'market_value':
        forecast_pv = raw_pv / (1 + initial_cost_rate)
        cost_text = f'（預估終值已扣買入手續費 {fee_buy*100:.3f}% + 滑價 {slippage*100:.3f}%）'
    else:
        forecast_pv = raw_pv
        cost_text = ''
    pv = raw_pv  # inputs.pv = market_value.total（不抽費）
    forecast_pv_value = forecast_pv  # 這個拿去算 forecast.fv
    pv_raw = raw_pv
    pv_cost_text = cost_text

    # 7) 三模式（使用含息 adj close 作為 daily return 來源）
    # 預設權重 = 〇、組合起始市值的權重（最後一個有效日 raw close × 股數，各自 normalize）
    # 主人 2026-08-31 18:45 更正：二、歷史真實績效 要用 〇 的權重，不是 buy & hold 第一天權重
    # → app.py 預算 mv_weights 並傳給 build_portfolio，避免 build_portfolio 內部用 adj close 算（會跟 raw close 不一致）
    mv_total = float(mv.get('total', 0))
    mv_weights: dict[str, float] | None = None
    if mv_total > 0 and mv.get('per_stock'):
        mv_weights = {
            item['ticker']: float(item['value'] / mv_total)
            for item in mv['per_stock']
        }
    # 優先序:user 輸入 > 〇、組合起始市值權重 > None(向後相容 → build_portfolio fallback)
    effective_weights = weights if weights else mv_weights
    # v3.1.2: 給前端 ⑤ 標題下的權重標註用（顯示「此次用了什麼權重」）
    if weights:
        weights_source = 'user'
    elif mv_weights is not None:
        weights_source = 'market_cap'
    elif effective_weights is None:
        weights_source = 'equal'  # build_portfolio 會 fallback 等權重
    else:
        weights_source = 'unknown'
    common_res = build_portfolio(prices_adj, mode='common', weights=effective_weights)
    dynamic_res = build_portfolio(prices_adj, mode='dynamic', weights=effective_weights)
    full_res = build_portfolio(prices_adj, mode='full', weights=effective_weights)

    # 7.5) Benchmark（adj close 才有含息比較性）
    benchmark = None
    if benchmark_id:
        try:
            bench_rows = client.get_stock_price(benchmark_id, start_date, end_date)
            bench_prices = prices_to_pivot({benchmark_id: bench_rows}, price_col='close')
            if not bench_prices.empty:
                # 該 ETF 也取息 + split 計算 adj（benchmark 該公平比較）
                b_start = min(r['date'] for r in bench_rows)
                bench_div = client.get_dividends(benchmark_id, b_start, end_date)
                bench_split = client.get_splits(benchmark_id, b_start, end_date)
                bench_prices = build_adjusted_close(
                    bench_prices,
                    {benchmark_id: bench_div},
                    {benchmark_id: bench_split},
                )
                # 裁到跟 dynamic 同期，公平對照
                bench_prices = bench_prices.loc[:dynamic_res.nav.index[-1]] if not dynamic_res.nav.empty else bench_prices
                benchmark = build_benchmark(bench_prices, ticker=benchmark_id)
        except FinMindError as e:
            benchmark = {'ticker': benchmark_id, 'error': str(e)}

    # 8) N-Year 預估：優先用 Common，不夠則退回 Dynamic / Full
    # 用 forecast_pv_value（抽費後）來算 FV
    forecast_basis = 'common'
    forecast = None
    for basis, res in (('common', common_res), ('dynamic', dynamic_res), ('full', full_res)):
        try:
            forecast = build_forecast(res.nav, n=n, pv=forecast_pv_value)
            forecast_basis = basis
            break
        except ForecastError:
            continue
    if forecast is None:
        raise ForecastError(
            f'三個模式的歷史長度都無法建立 N={n} 年 rolling outcome。'
            f'請縮短 N 年數，或加入上市更久的股票。'
        )
    forecast['basis'] = forecast_basis

    # 9) 個股歷史長度（加強版）- 一樣用 adj close 計算 5 個進階指標
    psh = per_stock_history(prices_adj)

    # 10) 組裝回傳
    # Return + Risk + MDD optimisation uses the same adjusted prices and the
    # same market-value weights as the legacy report; it never fabricates data.
    retirement_config = {
        'initial_balance': float(pv_raw) if pv_raw else 7_236_096,
        'horizon_years': int(body.get('v2_horizon_years', int(body.get('v2_retirement_end_age', 85)) - int(body.get('v2_current_age', 55)))),
        'n_simulations': int(body.get('v2_n_simulations', 1000)),
        'retirement_age': int(body.get('v2_retirement_age', 60)),
        'current_age': int(body.get('v2_current_age', body.get('current_age', 55))),
        'retirement_end_age': int(body.get('v2_retirement_end_age', 85)),
        'withdrawal_monthly': float(body.get('v2_withdrawal_monthly', 30_000)),
        'withdrawal_inflation': float(body.get('v2_withdrawal_inflation', 0.03)),
        'pension_monthly': float(body.get('v2_pension_monthly', 0.0)),
        'pension_inflation': float(body.get('v2_pension_inflation', 0.02)),
        'pension_start_age': int(body.get('v2_retirement_age', 60)),
        'special_expenses': body.get('v2_special_expenses') or [],
        'seed': 42,
    }
    optimization = build_optimization(
        prices_adj,
        current_weights=effective_weights or {},
        current_values={x['ticker']: x['value'] for x in mv.get('per_stock', [])},
        current_prices={x['ticker']: x['close'] for x in mv.get('per_stock', [])},
        shares=combined_shares,
        n_years=n,
        fees={'commission_buy': fee_buy, 'commission_sell': fee_sell,
              'slippage': slippage, 'tax_sell': tax_sell},
        risk_free_rate=float(body.get('v2_risk_free_rate', body.get('risk_free_rate', 0.015))),
        retirement_config=retirement_config,
    )
    # overview 改成驗收標準要求的欄位（start/end/rows/first_close/last_close）
    # 保留舊欄位（stocks/min_years/median_years/max_years）作 compatibility
    if psh:
        all_starts = [info['start'] for info in psh.values() if info.get('start')]
        all_ends = [info['end'] for info in psh.values() if info.get('end')]
        all_rows = [info['rows'] for info in psh.values() if info.get('rows')]
        all_first_close = [info['first_close'] for info in psh.values() if info.get('first_close') is not None]
        all_last_close = [info['last_close'] for info in psh.values() if info.get('last_close') is not None]
        overview = {
            # 驗收標準 #6 要的新欄位
            'start': min(all_starts) if all_starts else None,
            'end': max(all_ends) if all_ends else None,
            'rows': sum(all_rows) if all_rows else 0,
            'first_close': round(sum(all_first_close) / len(all_first_close), 2) if all_first_close else None,
            'last_close': round(sum(all_last_close) / len(all_last_close), 2) if all_last_close else None,
            # 舊欄位（compatibility）
            'stocks': len(matched),
            'min_years': min((v['years'] for v in psh.values()), default=0),
            'median_years': sorted([v['years'] for v in psh.values()])[len(psh) // 2] if psh else 0,
            'max_years': max((v['years'] for v in psh.values()), default=0),
        }
    else:
        overview = {
            'start': None,
            'end': None,
            'rows': 0,
            'first_close': None,
            'last_close': None,
            'stocks': 0,
            'min_years': 0,
            'median_years': 0,
            'max_years': 0,
        }

    # Phase 4.1: 組裝 result dict 後跑 model validation
    # Phase 6 (per Item 8): 單次呼叫 v2 extensions,避免重複抓 daily returns 4 次
    _v2 = _compute_v2_extensions(body, client, holdings, pv_raw, n)
    result = {
        'inputs': {
            'profile': profile,
            'user_tickers': user_tickers,
            'tickers': final_stock_ids,  # 驗證後的 stock_id 清單
            'shares': shares_map,
            'combined_shares': combined_shares,
            'n': n,
            'pv': pv,
            'pv_raw': pv_raw,
            'pv_source': pv_source,
            'pv_cost_text': pv_cost_text,
            'fees': {
                'fee_buy': fee_buy,
                'fee_sell': fee_sell,
                'tax_sell': tax_sell,
                'slippage': slippage,
            },
            'start_date': start_date,
            'end_date': end_date,
            'weights': weights,
            'invalid_tickers': invalid_tickers,
            'first_trading_days': first_trading_days,
            'short_history': short_history,
            'fetch_errors': fetch_errors,
            'ticker_match': {sid: {
                'stock_id': sid,
                'stock_name': info['stock_name'],
                'industry': info['industry_category'],
                'type': info['type'],
                'source': info['source'],
                'matched_from': info['matched_from'],
            } for sid, info in matched.items()},
        },
        # v3.1.2: ⑤ 標題下顯示「此次權重分配」（給前端 + 匯出報表用）
        'effective_weights': effective_weights,
        'weights_source': weights_source,
        'market_value': mv,
        'benchmark': benchmark,
        'common': _serialize_result(common_res, recent_n_years=n),
        'dynamic': _serialize_result(dynamic_res, recent_n_years=n),
        'full': _serialize_result(full_res, recent_n_years=n),
        'forecast': forecast,
        'history': {
            'overview': overview,
            'per_stock': psh,
            'per_stock_n_year': per_stock_n_year_window(prices, n, dividends_by_ticker, splits_by_ticker),
        },
        'optimization': optimization,
        'nav_series': {
            'common': _downsample_nav(common_res.nav),
            'dynamic': _downsample_nav(dynamic_res.nav),
            'full': _downsample_nav(full_res.nav),
        },
        # Phase 6 (per Item 8): 4 個欄位共用上面單次呼叫的 _v2 結果
        'monte_carlo': _v2.get('monte_carlo'),
        'sequence_risk': _v2.get('sequence_risk'),
        'risk_metrics': _v2.get('risk_metrics'),
        'retirement_inputs': _v2.get('retirement_inputs'),
        # v3.0.3 N8: card ⑥ 用。逐 ticker 獨立抓（避免 inner join 縮成最新 ticker 的範圍）
        'meta': _build_analyze_meta(client, [h.ticker for h in holdings], start_date, end_date),
    }
    # v3.0.4 P0 fix: card ⑥ 月報表走 fresh-start-per-month shares tracking
    # (跟一.6 同源,不被 cumulative shares 稀釋。沒 div/split cache 的 ticker
    #  graceful fallback 到 raw close)
    result['monthly_tickers'] = _build_monthly_tickers(
        holdings, client, start_date, end_date, n, dividends_by_ticker, splits_by_ticker,
    )
    # Phase 4.1: model validation（不 raise,只把結果塞 result['validation'],
    # 給前端選擇性顯示）。CI mode 可呼叫 raise_if_critical 改 raise。
    try:
        _validation = validate_all(result)
    except Exception as _ve:
        # validate 本身出錯 → fallback,放 SKIP report,不破壞整個 analyze 流程
        from lib.model_validator import Check, ValidationReport
        _validation = ValidationReport()
        _validation.add(Check(
            name='validate_all_runtime_error', severity='WARN', status='FAIL',
            message=f'validate_all 跳過:{_ve}',
        ))
        _validation.finalize()
    result['validation'] = _validation.to_dict()
    return result


def _build_monthly_tickers(holdings, client, start_date, end_date, n_years, dividends_by_ticker, splits_by_ticker):
    """v3.0.4 P0 fix: 算 card ⑥ 月報酬表(跟一.6 shares tracking 同源)。

    逐 ticker 走 raw close + dividend/split → compute_monthly_returns_via_shares_tracking
    沒 div/split cache 的 ticker graceful fallback 到 raw close。

    Window 限制 (跟舊 fallback 路徑對齊):
      window_end = end_date
      window_start = end_date - N 年 (N = n_years 參數,phase 6 item 1 規則)
      → 月報表只表達最近 N 年,避免被「上市第一天到今天」的累計 CAGR 吞掉

    Args:
        holdings: list[Holding(ticker, shares)]
        client: FinMindClient
        start_date, end_date: 'YYYY-MM-DD'
        n_years: N 年(從 request body 進來)
        dividends_by_ticker, splits_by_ticker: 字典 from upstream

    Returns:
        list[ticker_dict] (跟 compute_monthly_returns_via_shares_tracking 一樣)
    """
    from lib.monthly_returns import compute_monthly_returns_via_shares_tracking
    from lib.portfolio import prices_to_pivot

    rows_by_ticker: dict[str, list] = {}
    # 直接用 caller 傳進來的 dividends_by_ticker / splits_by_ticker
    # (上游 _run_analyze 已算好,不要重新從 cache 讀)
    for h in holdings:
        try:
            rows = client.get_stock_price(h.ticker, start_date, end_date, use_cache=True)
        except Exception:
            continue
        if not rows:
            continue
        rows_by_ticker[h.ticker] = rows

    if not rows_by_ticker:
        return []

    # 確保 caller 傳的 dict 有 keys(沒事件的就 [])
    divs_to_use = {tk: dividends_by_ticker.get(tk, []) for tk in rows_by_ticker}
    splits_to_use = {tk: splits_by_ticker.get(tk, []) for tk in rows_by_ticker}

    # N 年 window:跟舊 fallback 路徑同樣算法
    window_end_ts = pd.Timestamp(end_date)
    window_start_ts = window_end_ts - pd.DateOffset(years=n_years) if n_years > 0 else None

    prices_pivot = prices_to_pivot(rows_by_ticker, price_col='close')
    monthly_out = compute_monthly_returns_via_shares_tracking(
        prices_pivot,
        dividends_by_ticker=divs_to_use,
        splits_by_ticker=splits_to_use,
        window_start=window_start_ts.strftime('%Y-%m-%d') if window_start_ts is not None else None,
        window_end=end_date,
    )
    return monthly_out.get('tickers', [])


def _build_analyze_meta(client, tickers, start_date, end_date):
    """v3.0.4 P0 fix: 為每個 ticker 算含息 daily returns(跟月報表同源)。

    注意:這條 daily returns 仍用 cumulative adj close + pct_change。
    「逐月報酬表」會被 exporter 走 compute_monthly_returns_via_shares_tracking
    (fresh-start-per-month shares tracking) 覆蓋,不被 cumulative 稀釋。
    這裡只為 card ⑤ / dashboard JSON 提供 daily returns 給下游(若有)。
    """
    out = {}
    for ticker in tickers:
        rets, _fallback = _adj_close_daily_returns(
            ticker, client, start_date, end_date,
        )
        if rets is None or len(rets) == 0:
            continue
        out[ticker] = [
            {'date': d.strftime('%Y-%m-%d'), 'ret': float(r)}
            for d, r in rets.items()
        ]
    return {'daily_returns_by_ticker': out, 'start_date': start_date, 'end_date': end_date}


def _adj_close_daily_returns(
    ticker: str,
    client: FinMindClient,
    start_date: str,
    end_date: str,
) -> tuple[pd.Series | None, bool]:
    """v3.0.4 P0 fix: 含息還原後的 daily returns(graceful fallback)。

    邏輯:
      1. 抓 raw close + dividends + splits(走 cache)
      2. 走 build_adjusted_close → 含息 adj close
      3. pct_change → daily returns
      4. 若 div/split cache 都空 → fallback 到 raw close(等同 v3.0.3 行為)

    Returns:
        (returns_series, fallback_to_raw)
        - returns_series: pd.Series 含 date index, name=ticker
        - fallback_to_raw: True 表示該 ticker 走 graceful fallback(沒事件)
          呼叫端可以 log warning

    Fallback 安全性:
      - build_adjusted_close(prices, {}, {}) = prices(沒事件就當 raw)
      - 數學結果等同 raw close pct_change
      - 不會 silently 壞掉,只是跟原本一樣
    """
    try:
        rows = client.get_stock_price(ticker, start_date, end_date, use_cache=True)
    except Exception:
        return None, False
    if not rows:
        return None, False

    # 取 div/split(若 cache miss 會走 API,失敗就 graceful empty)
    try:
        divs = client.get_dividends(ticker, start_date, end_date)
    except Exception:
        divs = []
    try:
        splits = client.get_splits(ticker, start_date, end_date)
    except Exception:
        splits = []

    has_events = bool(divs) or bool(splits)

    df = pd.DataFrame(rows)
    df['date'] = pd.to_datetime(df['date'])
    df = df.set_index('date').sort_index()
    pivot = pd.DataFrame({ticker: df['close']})
    adj = build_adjusted_close(
        pivot,
        dividends_by_ticker={ticker: divs} if divs else {},
        splits_by_ticker={ticker: splits} if splits else {},
    )
    rets = adj[ticker].pct_change().dropna()
    # v3.0.4 fix: 過濾 inf (close=0 → pct_change(±∞))
    rets = rets.replace([float('inf'), float('-inf')], float('nan')).dropna()

    if len(rets) > 0:
        rets.name = ticker
        return rets, not has_events
    return None, not has_events


def _compute_v2_extensions(
    body: dict,
    client: FinMindClient,
    holdings,
    pv_raw: float,
    n_years: int = 5,
) -> dict:
    """B4 整合：拿 FinMind daily 股價 + weights → 跑 F1 Monte Carlo + F2 Sequence Risk + F3/F6 risk metrics
    修股宝 16:11 「web 看不到 F1 的內容」:讓 /api/analyze 返回 F1 + F2 + F3 + F6。

    默認開啟,body.get('enable_v2') = False 可關(重 plot 路徑)
    默認 n=1000(約 3-5s/feature),body.get('v2_n_simulations') 可調
    F1/F2/F3 任何一個失敗都不會 break analyze(以 None 回傳)
    """
    if body.get('enable_v2') is False:
        return {'monte_carlo': None, 'sequence_risk': None, 'risk_metrics': None}

    n_sims = int(body.get('v2_n_simulations', 1000))
    initial = float(pv_raw) if pv_raw else 7_236_096
    # F2 retirement horizon is independent from future-investment N years.
    # Default retirement assessment is current age -> age 90; explicit
    # v2_horizon_years remains an API override.
    current_age = int(body.get('v2_current_age', body.get('current_age', 55)))
    retirement_age = int(body.get('v2_retirement_age', body.get('retirement_age', 60)))
    retirement_end_age = int(body.get('v2_retirement_end_age', 85))
    horizon = int(body.get('v2_horizon_years', retirement_end_age - current_age))
    # Phase 6 (Item 8): retirement_end_age also feeds retirement_inputs.
    forecast_horizon = int(body.get('v2_forecast_horizon', body.get('n', n_years)))

    out: dict = {'monte_carlo': None, 'sequence_risk': None, 'risk_metrics': None}

    # 取 daily returns
    try:
        daily_returns, _meta = _fetch_daily_portfolio_returns(
            body.get('profile', 'kadela_stock'),
            client=client,
        )
    except _BadInput as e:
        # F1/F2/F3/F6 默默 NULL 很糟糕(master 2026-08-27 09:44 問「為什麼隱藏」)
        # 至少記 log + 在 response 留 hint,前端可顯示
        logger.warning(
            f'_compute_v2_extensions skip(v2 區塊全部 None):daily_returns 取不到 → {e}'
        )
        skip_meta = {'skip_reason': f'daily_returns 取不到:{e}'}
        # v3.0.3: 如果是 normalize gate 失敗,把 code/failed 一起帶出去
        if e.code:
            skip_meta['code'] = e.code
            skip_meta['failed'] = e.details.get('failed', [])
        out['_meta'] = skip_meta
        return out

    # F1 Monte Carlo — Phase 5 (F5): 純投資推估 horizon 應等於 N (n_years),不是退休 horizon
    try:
        mc_cfg = MonteCarloConfig(
            initial_balance=initial,
            horizon_years=n_years,   # F1 = 投資推估 = N
            n_simulations=n_sims,
            annual_withdrawal=0.0,
            seed=42,
        )
        mc_result = simulate_monte_carlo(daily_returns, mc_cfg)
        out['monte_carlo'] = mc_result.to_dict()
    except (MonteCarloError, ValueError, ArithmeticError) as e:
        logger.warning(f'_compute_v2_extensions F1 失敗:{e}')

    # F2 Sequence Risk(股宝 5% rule = 30K/月)
    try:
        sr_cfg = SequenceRiskConfig(
            initial_balance=initial,
            horizon_years=horizon,
            n_simulations=n_sims,
            retirement_age=retirement_age,
            current_age=current_age,            # Phase 1.1: 年齡模型 (退休前不扣款)
            retirement_end_age=retirement_end_age,
            withdrawal_monthly=float(body.get('v2_withdrawal_monthly', 30_000)),
            withdrawal_inflation=float(body.get('v2_withdrawal_inflation', 0.03)),
            pension_monthly=float(body.get('v2_pension_monthly', 0.0)),
            pension_inflation=float(body.get('v2_pension_inflation', 0.02)),
            pension_start_age=retirement_age,
            special_expenses=body.get('v2_special_expenses') or [],
            seed=42,
        )
        sr_result = simulate_sequence_risk(daily_returns, sr_cfg)
        out['sequence_risk'] = sr_result.to_dict()
    except (SequenceRiskError, ValueError, ArithmeticError) as e:
        logger.warning(f'_compute_v2_extensions F2 失敗:{e}')

    # F3 + F6 risk metrics (VaR/CVaR + Sharpe with Rf)
    try:
        out['risk_metrics'] = run_risk_metrics(
            daily_returns,
            {
                'confidence_levels': [0.95, 0.99],
                'horizon_days': [1, 21, 252],
                'risk_free_rate': float(body.get('v2_risk_free_rate', 0.015)),
                'risk_free_source': body.get('v2_risk_free_source', 'tw_10y_bond'),
            },
        )
    except (RiskMetricsError, ValueError) as e:
        logger.warning(f'_compute_v2_extensions F3+F6 失敗:{e}')

    # Phase 6 (Item 8): retirement_inputs 給 report 頂部 header 渲染
    # (目前年齡 / 退休年齡 / 退休評估終點 / 退休評估期 / 未來推估終點年齡)
    out['retirement_inputs'] = {
        'current_age': current_age,
        'retirement_age': retirement_age,
        'retirement_end_age': retirement_end_age,
        'forecast_horizon': forecast_horizon,
        'retirement_horizon': retirement_end_age - current_age,
        'forecast_end_age': current_age + forecast_horizon,
    }

    return out


def _serialize_result(r, recent_n_years: int | None = None) -> dict:
    """把 PortfolioResult 轉 JSON-safe dict

    Args:
        r: PortfolioResult
        recent_n_years: 若指定, 計算「最近 N 年真實績效」(rebase 到 1.0 起點)
                       None = 不算 (向後相容)
    """
    return {
        'mode': r.mode,
        'metrics': r.metrics,
        'recent_metrics': (
            recent_n_year_metrics(r.nav, recent_n_years)
            if recent_n_years is not None else None
        ),
        'nav': _downsample_nav(r.nav),
        'pct_active': (
            [{'date': str(d.date()), 'n': int(v)} for d, v in r.pct_active.items()]
            if r.pct_active is not None else None
        ),
    }


def _downsample_nav(nav, max_points: int = 500) -> list[dict]:
    """NAV 太長時下採樣到 ~500 點（避免 JSON 太大）"""
    if nav is None or nav.empty:
        return []
    if len(nav) <= max_points:
        return [{'date': str(d.date()), 'nav': float(v)} for d, v in nav.items()]
    step = max(1, len(nav) // max_points)
    sampled = nav.iloc[::step]
    if sampled.index[-1] != nav.index[-1]:
        # 確保最後一點是真正的 end-of-data
        sampled = pd_concat_safe(sampled, nav.iloc[[-1]])
    return [{'date': str(d.date()), 'nav': float(v)} for d, v in sampled.items()]


def pd_concat_safe(*series) -> 'pd.Series':
    """小工具：concat 多個 Series 並去重（by index）"""
    import pandas as pd
    s = pd.concat(list(series))
    s = s[~s.index.duplicated(keep='last')].sort_index()
    return s


# ────────────── 啟動 ──────────────
app = create_app()


if __name__ == '__main__':
    import os
    import sys
    # Windows console (cp950) can't print emoji; use ASCII banner
    # 原本是 🚀 / 📁 emoji，避免 UnicodeEncodeError
    port = int(os.environ.get('PORT', 5000))
    host = os.environ.get('HOST', '0.0.0.0')
    print(f'[Portfolio Forecast] starting: http://{host}:{port}/')
    print(f'[Portfolio Forecast] root: {ROOT_DIR}')
    app.run(host=host, port=port, debug=False, threaded=True)
