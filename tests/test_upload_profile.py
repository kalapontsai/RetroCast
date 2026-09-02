"""
tests/test_upload_profile.py
- v3.0.3: 測試 /api/upload_profile 的 normalize gate
- 涵蓋: happy path / unknown ticker / 既有檔覆蓋 / idempotent / format errors
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app as _app_mod  # noqa: E402
from app import app  # noqa: E402
from lib import finmind as _finmind_mod  # noqa: E402
from lib.csv_loader import load_portfolio_csv  # noqa: E402


# ───────── Test fixtures ─────────
@pytest.fixture
def tmp_profile_dir(tmp_path, monkeypatch):
    """把 USER_PROFILE_DIR 指向 tmp,不動真實 user_profile/"""
    monkeypatch.setattr(_app_mod, 'USER_PROFILE_DIR', tmp_path)
    return tmp_path


@pytest.fixture
def mock_stock_list(monkeypatch):
    """塞 fake stock list,避免打真 FinMind API"""
    rows = [
        {'stock_id': '0050', 'stock_name': '元大台灣50', 'industry_category': 'ETF', 'type': 'twse'},
        {'stock_id': '0056', 'stock_name': '元大高股息', 'industry_category': 'ETF', 'type': 'twse'},
        {'stock_id': '00631L', 'stock_name': '元大台灣50正2', 'industry_category': 'ETF', 'type': 'twse'},
        {'stock_id': '2002', 'stock_name': '中鋼', 'industry_category': '鋼鐵', 'type': 'twse'},
        {'stock_id': '2412', 'stock_name': '中華電', 'industry_category': '通信', 'type': 'twse'},
        {'stock_id': '2330', 'stock_name': '台積電', 'industry_category': '半導體', 'type': 'twse'},
        {'stock_id': '2885', 'stock_name': '元大金', 'industry_category': '金融', 'type': 'twse'},
        {'stock_id': '2881', 'stock_name': '富邦金', 'industry_category': '金融', 'type': 'twse'},
        {'stock_id': '2891', 'stock_name': '中信金', 'industry_category': '金融', 'type': 'twse'},
    ]
    monkeypatch.setattr(
        _finmind_mod.FinMindClient, 'get_stock_list', lambda self, **kw: rows,
    )
    return rows


@pytest.fixture
def client():
    return app.test_client()


def _post_upload(client, csv_bytes: bytes, filename: str = 'test.csv'):
    return client.post(
        '/api/upload_profile',
        data={'file': (io.BytesIO(csv_bytes), filename)},
        content_type='multipart/form-data',
    )


# ───────── happy path: 50 → 0050 ─────────
def test_upload_normalizes_50_to_0050(client, tmp_profile_dir, mock_stock_list):
    resp = _post_upload(client, b'50,195000\n2002,1000\n', 'myprofile.csv')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['name'] == 'myprofile'
    assert data['normalized'] is True
    assert data['changes'] == [
        {'line': 1, 'from': '50', 'to': '0050', 'name': '元大台灣50'},
    ]
    # 寫回的檔案內容已 normalize
    out = tmp_profile_dir / 'myprofile.csv'
    assert out.is_file()
    content = out.read_bytes().decode('utf-8-sig')
    assert '0050,195000' in content
    assert '\n50,195000\n' not in content  # 不再有 raw 50


def test_upload_idempotent_when_already_canonical(client, tmp_profile_dir, mock_stock_list):
    """已是 canonical 形式 → 200, normalized=False, changes=[]"""
    resp = _post_upload(client, b'0050,100\n2002,500\n', 'good.csv')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['normalized'] is False
    assert data['changes'] == []


def test_upload_normalizes_multiple_tickers(client, tmp_profile_dir, mock_stock_list):
    """多個 ticker 同時 normalize"""
    resp = _post_upload(
        client,
        b'50,195000\n56,5000\n00631L,10000\n2330,500\n',
        'multi.csv',
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['normalized'] is True
    change_pairs = {(c['from'], c['to']) for c in data['changes']}
    assert change_pairs == {('50', '0050'), ('56', '0056')}


# ───────── 失敗: 任一 ticker 對不上 → 不寫檔 ─────────
def test_upload_unknown_ticker_returns_400(client, tmp_profile_dir, mock_stock_list):
    resp = _post_upload(client, b'50,100\n9999,500\n', 'bad.csv')
    assert resp.status_code == 400
    data = resp.get_json()
    assert data['code'] == 'TICKER_NOT_FOUND'
    assert '1 個代號無法辨識' in data['error']
    assert len(data['failed']) == 1
    assert data['failed'][0]['ticker'] == '9999'
    assert data['failed'][0]['line'] == 2
    # 檔案不落地
    assert not (tmp_profile_dir / 'bad.csv').exists()
    # 也不留 tmp
    assert list(tmp_profile_dir.glob('*.tmp')) == []


def test_upload_multiple_unknown_tickers(client, tmp_profile_dir, mock_stock_list):
    """多個未知 ticker → 全部列出來"""
    resp = _post_upload(client, b'50,100\n9999,500\n8888,200\n', 'bad.csv')
    assert resp.status_code == 400
    data = resp.get_json()
    assert data['code'] == 'TICKER_NOT_FOUND'
    assert '2 個代號無法辨識' in data['error']
    tickers_failed = {f['ticker'] for f in data['failed']}
    assert tickers_failed == {'9999', '8888'}
    assert not (tmp_profile_dir / 'bad.csv').exists()


def test_upload_failed_does_not_leave_tmp(client, tmp_profile_dir, mock_stock_list):
    """失敗時 tmp 也要清乾淨"""
    resp = _post_upload(client, b'9999,100\n', 'will_fail.csv')
    assert resp.status_code == 400
    # 沒有任何殘留
    leftovers = list(tmp_profile_dir.iterdir())
    assert leftovers == []


# ───────── 既有檔覆蓋 ─────────
def test_upload_overwrites_existing_file(client, tmp_profile_dir, mock_stock_list):
    """重複上傳同名檔 → 覆蓋並 normalize"""
    out = tmp_profile_dir / 'reupload.csv'
    out.write_text('9999,999\n', encoding='utf-8')

    resp = _post_upload(client, b'50,100\n2002,200\n', 'reupload.csv')
    assert resp.status_code == 200

    # 舊內容完全消失
    content = out.read_bytes().decode('utf-8-sig')
    assert '9999' not in content
    assert '0050,100' in content


# ───────── 既有錯誤行為不變 ─────────
def test_upload_no_file_returns_400(client, tmp_profile_dir, mock_stock_list):
    resp = client.post('/api/upload_profile', data={}, content_type='multipart/form-data')
    assert resp.status_code == 400
    assert resp.get_json()['error'] == '沒有收到檔案'


def test_upload_empty_filename_returns_400(client, tmp_profile_dir, mock_stock_list):
    resp = client.post(
        '/api/upload_profile',
        data={'file': (io.BytesIO(b'50,100\n'), '')},
        content_type='multipart/form-data',
    )
    assert resp.status_code == 400
    assert resp.get_json()['error'] == '檔名是空的'


def test_upload_non_csv_extension_returns_400(client, tmp_profile_dir, mock_stock_list):
    resp = _post_upload(client, b'50,100\n', 'notcsv.txt')
    assert resp.status_code == 400
    assert resp.get_json()['error'] == '只接受 .csv 檔案'


def test_upload_malformed_csv_returns_400(client, tmp_profile_dir, mock_stock_list):
    """格式錯誤(漏逗號) → 既有 400,不落地"""
    resp = _post_upload(client, b'50 100\n', 'malformed.csv')
    assert resp.status_code == 400
    data = resp.get_json()
    assert 'CSV 格式錯誤' in data['error']
    assert not (tmp_profile_dir / 'malformed.csv').exists()


def test_upload_invalid_utf8_returns_400(client, tmp_profile_dir, mock_stock_list):
    """編碼錯誤 → 既有 400"""
    # Big5 bytes — 無法解 UTF-8
    big5 = b'\xa4\x40\xa4\x41\n'  # 中字 in big5
    resp = _post_upload(client, big5, 'big5.csv')
    assert resp.status_code == 400
    data = resp.get_json()
    assert '編碼錯誤' in data['error']


# ───────── 完整 round-trip ─────────
def test_uploaded_file_is_reloadable_as_normalized_csv(client, tmp_profile_dir, mock_stock_list):
    """上傳後的檔案 load 進來,ticker 應該都是 canonical"""
    _post_upload(client, b'50,195000\n2002,1000\n', 'rt.csv')
    out = tmp_profile_dir / 'rt.csv'
    holdings = load_portfolio_csv(out)
    tickers = [h.ticker for h in holdings]
    assert tickers == ['0050', '2002']  # 50 → 0050, 2002 already canonical


# ───────── 用真實 kadela_stock.csv 跑完整流程 ─────────
def test_upload_real_kadela_stock_normalizes(client, tmp_profile_dir, mock_stock_list):
    src = ROOT / 'user_profile' / 'kadela_stock.csv'
    if not src.is_file():
        pytest.skip(f'{src} not found')
    csv_bytes = src.read_bytes()
    resp = _post_upload(client, csv_bytes, 'kadela_stock.csv')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['normalized'] is True
    # 50 → 0050 是唯一會被改的(其他都是 canonical)
    change_pairs = {(c['from'], c['to']) for c in data['changes']}
    assert ('50', '0050') in change_pairs
    # 寫回的檔案沒有 raw '50,' 開頭(只有 '0050,')
    out = tmp_profile_dir / 'kadela_stock.csv'
    content = out.read_bytes().decode('utf-8-sig')
    lines = content.split('\n')
    tickers_in_file = {line.split(',')[0] for line in lines if line.strip()}
    assert '50' not in tickers_in_file
    assert '0050' in tickers_in_file
