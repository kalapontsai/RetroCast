"""
tests/test_csv_loader.py
- 測試 csv_loader 對各種格式的 (Ticker, Shares) CSV 容錯
"""
import sys
from pathlib import Path

import pytest

# 確保 lib/ 在 path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib.csv_loader import (
    CSVLintError, Holding, _parse_csv_preserving_lines, list_profile_csvs,
    load_portfolio_csv,
)


def test_simple_two_columns():
    """無 header，兩欄乾淨數字"""
    csv = "2330,387\n6208,3713\n"
    h = load_portfolio_csv(csv)
    assert h == [Holding('2330', 387), Holding('6208', 3713)]


def test_with_header_english():
    csv = "Ticker,Shares\n2330,387\n6208,3713\n"
    h = load_portfolio_csv(csv)
    assert h == [Holding('2330', 387), Holding('6208', 3713)]


def test_with_header_chinese():
    csv = '代號,股數\n2330,387\n6208,"3,713"\n'
    h = load_portfolio_csv(csv)
    assert h == [Holding('2330', 387), Holding('6208', 3713)]


def test_thousands_separator_quoted():
    """使用者範例：shares 帶千分位"""
    csv = '''50,"21,315"
6208,"3,713"
2330,387
'''
    h = load_portfolio_csv(csv)
    assert h == [Holding('50', 21315), Holding('6208', 3713), Holding('2330', 387)]


def test_real_liyu_stock_fixture():
    """用 user_profile/liyu_stock.csv 跑一次（31 筆）"""
    f = ROOT / 'user_profile' / 'liyu_stock.csv'
    if not f.is_file():
        pytest.skip(f'{f} not found')
    h = load_portfolio_csv(f)
    assert len(h) == 31
    # 檢查第一筆
    assert h[0].ticker == '50'
    assert h[0].shares == 21315


def test_duplicate_ticker_sums():
    csv = "Ticker,Shares\n2330,100\n2330,250\n"
    h = load_portfolio_csv(csv)
    assert h == [Holding('2330', 350)]


def test_empty_file():
    with pytest.raises(CSVLintError):
        load_portfolio_csv('')


def test_only_header():
    with pytest.raises(CSVLintError):
        load_portfolio_csv('Ticker,Shares\n')


def test_missing_ticker_column():
    """純數字當 header 無 ticker 別名 → 視為無 header，要求兩欄"""
    with pytest.raises(CSVLintError):
        load_portfolio_csv('Foo,Bar\n2330,100\n')


def test_blank_rows_skipped():
    csv = "Ticker,Shares\n\n2330,100\n\n"
    h = load_portfolio_csv(csv)
    assert h == [Holding('2330', 100)]


def test_list_profile_csvs():
    """讀 user_profile/ 應該找得到 liyu_stock.csv"""
    profiles = list_profile_csvs(ROOT / 'user_profile')
    assert 'liyu_stock' in profiles


# ───────── v3.0.3: normalize_profile_csv ─────────
@pytest.fixture
def mock_finmind(monkeypatch):
    """塞 fake stock list 進 FinMindClient"""
    from lib import finmind as _finmind_mod
    rows = [
        {'stock_id': '0050', 'stock_name': '元大台灣50', 'industry_category': 'ETF', 'type': 'twse'},
        {'stock_id': '0056', 'stock_name': '元大高股息', 'industry_category': 'ETF', 'type': 'twse'},
        {'stock_id': '00631L', 'stock_name': '元大台灣50正2', 'industry_category': 'ETF', 'type': 'twse'},
        {'stock_id': '2002', 'stock_name': '中鋼', 'industry_category': '鋼鐵', 'type': 'twse'},
        {'stock_id': '2412', 'stock_name': '中華電', 'industry_category': '通信', 'type': 'twse'},
        {'stock_id': '2330', 'stock_name': '台積電', 'industry_category': '半導體', 'type': 'twse'},
        {'stock_id': '6208', 'stock_name': '日揚', 'industry_category': '半導體', 'type': 'tpex'},
        {'stock_id': '2881', 'stock_name': '富邦金', 'industry_category': '金融', 'type': 'twse'},
        {'stock_id': '2885', 'stock_name': '元大金', 'industry_category': '金融', 'type': 'twse'},
        {'stock_id': '2891', 'stock_name': '中信金', 'industry_category': '金融', 'type': 'twse'},
    ]
    monkeypatch.setattr(_finmind_mod.FinMindClient, 'get_stock_list', lambda self, **kw: rows)
    return rows


def _write_csv(tmp_path: Path, name: str, content: bytes) -> Path:
    p = tmp_path / name
    p.write_bytes(content)
    return p


def test_normalize_basic_50_to_0050(tmp_path, mock_finmind):
    """happy path: 50 → 0050,寫回後檔案內容正確"""
    p = _write_csv(tmp_path, 'test.csv', b'50,195000\n2002,1000\n')
    from lib.csv_loader import normalize_profile_csv
    result = normalize_profile_csv(p)
    assert result.applied is True
    assert result.failed == []
    assert len(result.changes) == 1
    assert result.changes[0] == {'line': 1, 'from': '50', 'to': '0050', 'name': '元大台灣50'}
    # 檔案內容
    assert p.read_bytes() == b'\xef\xbb\xbf0050,195000\n2002,1000\n'


def test_normalize_idempotent(tmp_path, mock_finmind):
    """再跑一次已 normalized 的檔 → applied=False, changes=[]"""
    p = _write_csv(tmp_path, 'test.csv', b'0050,195000\n2002,1000\n')
    from lib.csv_loader import normalize_profile_csv
    r1 = normalize_profile_csv(p)
    r2 = normalize_profile_csv(p)
    assert r1.applied is False
    assert r2.applied is False
    assert r1.changes == []
    assert r2.changes == []


def test_normalize_unknown_ticker_does_not_write(tmp_path, mock_finmind):
    """任一 ticker 找不到 → applied=False, failed 列出來,檔案不動"""
    original = b'50,195000\n9999,1000\n'
    p = _write_csv(tmp_path, 'test.csv', original)
    from lib.csv_loader import normalize_profile_csv
    result = normalize_profile_csv(p)
    assert result.applied is False
    assert len(result.failed) == 1
    assert result.failed[0]['ticker'] == '9999'
    assert result.failed[0]['line'] == 2
    # 檔案完全沒變(atomic rename 保證)
    assert p.read_bytes() == original


def test_normalize_preserves_crlf(tmp_path, mock_finmind):
    """Windows-style CRLF 行尾要保留"""
    p = _write_csv(tmp_path, 'test.csv', b'50,195000\r\n2002,1000\r\n')
    from lib.csv_loader import normalize_profile_csv
    result = normalize_profile_csv(p)
    assert result.applied is True
    # BOM + CRLF
    assert p.read_bytes() == b'\xef\xbb\xbf0050,195000\r\n2002,1000\r\n'


def test_normalize_no_trailing_newline(tmp_path, mock_finmind):
    """檔案沒結尾換行 → 寫回後也沒"""
    p = _write_csv(tmp_path, 'test.csv', b'50,195000\n2002,1000')
    from lib.csv_loader import normalize_profile_csv
    result = normalize_profile_csv(p)
    assert result.applied is True
    assert p.read_bytes() == b'\xef\xbb\xbf0050,195000\n2002,1000'


def test_normalize_with_header(tmp_path, mock_finmind):
    """有 header 的 CSV → header 不動,只改 data 列"""
    p = _write_csv(tmp_path, 'test.csv', b'Ticker,Shares\n50,195000\n2002,1000\n')
    from lib.csv_loader import normalize_profile_csv
    result = normalize_profile_csv(p)
    assert result.applied is True
    # line 2 是第一筆 data(因為 line 1 是 header)
    assert result.changes[0]['line'] == 2
    assert result.changes[0]['from'] == '50'
    assert result.changes[0]['to'] == '0050'
    # 重讀驗 header 還在
    content = p.read_bytes().decode('utf-8-sig')
    lines = content.split('\n')
    assert lines[0] == 'Ticker,Shares'
    assert lines[1] == '0050,195000'
    assert lines[2] == '2002,1000'


def test_normalize_no_changes_when_already_canonical(tmp_path, mock_finmind):
    """全部都是 canonical 形式 → applied=False"""
    p = _write_csv(tmp_path, 'test.csv', b'0050,195000\n2002,1000\n00631L,10000\n')
    from lib.csv_loader import normalize_profile_csv
    result = normalize_profile_csv(p)
    assert result.applied is False
    assert result.changes == []
    assert result.failed == []
    # 檔案完全沒動
    assert p.read_bytes() == b'0050,195000\n2002,1000\n00631L,10000\n'


def test_normalize_multiple_tickers(tmp_path, mock_finmind):
    """多個 ticker 同時要 normalize"""
    p = _write_csv(tmp_path, 'test.csv', b'50,195000\n56,5000\n2002,1000\n2330,500\n')
    from lib.csv_loader import normalize_profile_csv
    result = normalize_profile_csv(p)
    assert result.applied is True
    assert {c['from'] for c in result.changes} == {'50', '56'}
    assert {c['to'] for c in result.changes} == {'0050', '0056'}
    # 2002/2330 already canonical → 不在 changes 內


def test_normalize_dedup_same_ticker(tmp_path, mock_finmind):
    """同 ticker 出現兩次 → match 只跑一次,changes 只有一筆"""
    p = _write_csv(tmp_path, 'test.csv', b'50,100\n50,200\n2002,50\n')
    from lib.csv_loader import normalize_profile_csv
    result = normalize_profile_csv(p)
    # 只有 line 1 (50) 和 line 2 (50) 都要改,
    # 但因為 line 1 = line 2 同一個 ticker,實作上兩行都會改
    assert result.applied is True
    assert {c['from'] for c in result.changes} == {'50'}
    assert all(c['to'] == '0050' for c in result.changes)


def test_normalize_preserves_quoted_shares(tmp_path, mock_finmind):
    """shares 帶千分位引號 → ticker 改時不要搞壞 quotes"""
    p = _write_csv(tmp_path, 'test.csv', b'50,"195,000"\n2002,"1,000"\n')
    from lib.csv_loader import normalize_profile_csv
    result = normalize_profile_csv(p)
    assert result.applied is True
    # 重讀驗證 quotes 還在
    from lib.csv_loader import load_portfolio_csv
    holdings = load_portfolio_csv(p)
    assert len(holdings) == 2
    assert holdings[0].ticker == '0050'
    assert holdings[0].shares == 195000
    assert holdings[1].shares == 1000


def test_normalize_returns_NormalizeResult_dataclass(tmp_path, mock_finmind):
    """回傳值是 NormalizeResult 實例,有 to_dict() 方法"""
    p = _write_csv(tmp_path, 'test.csv', b'50,100\n')
    from lib.csv_loader import normalize_profile_csv, NormalizeResult
    result = normalize_profile_csv(p)
    assert isinstance(result, NormalizeResult)
    d = result.to_dict()
    assert 'applied' in d
    assert 'changes' in d
    assert 'failed' in d


def test_normalize_atomic_write(tmp_path, mock_finmind):
    """atomic rename: 寫入過程中不會留下 .tmp 檔"""
    p = _write_csv(tmp_path, 'test.csv', b'50,100\n')
    from lib.csv_loader import normalize_profile_csv
    normalize_profile_csv(p)
    # 不應有 .tmp 殘留
    tmp_files = list(tmp_path.glob('*.tmp'))
    assert tmp_files == []


def test_normalize_file_not_found(tmp_path, mock_finmind):
    """檔案不存在 → raise CSVLintError"""
    from lib.csv_loader import normalize_profile_csv, CSVLintError
    p = tmp_path / 'nonexistent.csv'
    with pytest.raises(CSVLintError):
        normalize_profile_csv(p)


def test_normalize_empty_csv(tmp_path, mock_finmind):
    """空 CSV → raise CSVLintError,不算 normalize 成功"""
    from lib.csv_loader import normalize_profile_csv, CSVLintError
    p = _write_csv(tmp_path, 'test.csv', b'')
    with pytest.raises(CSVLintError):
        normalize_profile_csv(p)


def test_normalize_with_real_kadela_stock(tmp_path, mock_finmind):
    """用真實 kadela_stock.csv 跑一次,預期 50→0050,其他不變"""
    src = ROOT / 'user_profile' / 'kadela_stock.csv'
    if not src.is_file():
        pytest.skip(f'{src} not found')
    # Copy to tmp so we don't modify the real one
    p = tmp_path / 'kadela_stock.csv'
    p.write_bytes(src.read_bytes())

    from lib.csv_loader import normalize_profile_csv
    result = normalize_profile_csv(p)

    # 預期:只有 50 要變 0050;00631L, 2002, 2412, 2891 已是 canonical
    assert result.applied is True
    assert result.failed == []
    # changes 至少要含 50→0050
    assert any(c['from'] == '50' and c['to'] == '0050' for c in result.changes)
    # 寫回後重讀,沒有 raw '50' 留在第一欄(只有 0050)
    from lib.csv_loader import load_portfolio_csv
    holdings = load_portfolio_csv(p)
    tickers = [h.ticker for h in holdings]
    assert '50' not in tickers
    assert '0050' in tickers
    # shares 沒變
    assert sum(h.shares for h in holdings) > 0


# ───────── v3.0.4 fix: 異常行尾 sanitize fallback ─────────
def test_double_cr_newline_fallback():
    """有些編輯器把 Enter 存成 \\r\\r (雙 CR) → csv.reader 在 unquoted field 看到 newline 就爆
    v3.0.4 fix: 偵測到 new-line character error 時, 自動 normalize 為 \\n 重試
    """
    # 構造 \\r\\r 行尾的 CSV（模擬 sample.csv 實際情況）
    raw = '50,"1,000"\r\r6208,"1,000"\r\r2330,"1,000"\r\r'
    lines, parsed, has_header = _parse_csv_preserving_lines(raw)
    assert has_header is False
    assert len(parsed) == 3, f'預期 3 筆, 拿到 {len(parsed)}'
    assert parsed[0]['ticker_raw'] == '50'
    assert parsed[1]['ticker_raw'] == '6208'
    assert parsed[2]['ticker_raw'] == '2330'
    # line_no 全部正確 (因為 sanitize 後重算)
    for i, row in enumerate(parsed):
        assert row['line_no'] == i + 1


def test_lone_cr_newline_fallback():
    """純 \\r (Mac 舊式) → 同樣需要 sanitize"""
    raw = '0050,"1000"\r2330,"500"\r'
    lines, parsed, has_header = _parse_csv_preserving_lines(raw)
    assert len(parsed) == 2
    assert parsed[0]['ticker_raw'] == '0050'
    assert parsed[1]['ticker_raw'] == '2330'


def test_normal_crlf_still_works():
    """正常 CRLF 不走 fallback, 一致行為"""
    raw = '0050,"1000"\r\n2330,"500"\r\n'
    lines, parsed, has_header = _parse_csv_preserving_lines(raw)
    assert len(parsed) == 2
    assert parsed[0]['ticker_raw'] == '0050'
    assert parsed[1]['ticker_raw'] == '2330'


def test_real_sample_csv_analyzable():
    """user_profile/sample.csv (原始有 \\r\\r, 但 normalize 後已是 LF + 0050)
    走完整解析不該爆"""
    from pathlib import Path
    f = ROOT / 'user_profile' / 'sample.csv'
    if not f.is_file():
        pytest.skip(f'{f} not found')
    text = f.read_bytes().decode('utf-8-sig')
    lines, parsed, has_header = _parse_csv_preserving_lines(text)
    assert has_header is False
    assert len(parsed) >= 1
    # normalize 後 50→0050 + 行尾→\n, 所以第一行 ticker 是 '0050'
    assert parsed[0]['ticker_raw'] == '0050'


def test_raw_double_cr_sample_pattern(tmp_path):
    """重現『sample.csv 原始樣貌』的情境:
    a) 寫一個有 \\\\r\\\\r 的 tmp CSV 進檔
    b) 走 _parse_csv_preserving_lines 應該不爆 (走 fallback)
    c) parsed[0] 抓到 '50' (尚未被 normalize_profile_csv 寫回)"""
    raw = b'\xef\xbb\xbf50,"1,000"\r\r6208,"1,000"\r\r'
    f = tmp_path / 'sample_raw.csv'
    f.write_bytes(raw)
    text = f.read_bytes().decode('utf-8-sig')
    lines, parsed, has_header = _parse_csv_preserving_lines(text)
    assert has_header is False
    assert parsed[0]['ticker_raw'] == '50'
    assert parsed[1]['ticker_raw'] == '6208'
