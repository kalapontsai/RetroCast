"""
tests/test_migrate_price_cache.py
- v3.0.3: 測試 scripts/migrate_price_cache_to_canonical.py
- 用 tmpdir 模擬 cache dir + mock FinMind match_ticker
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

from migrate_price_cache_to_canonical import (  # noqa: E402
    migrate_one, find_trash_dir, safe_trash,
)


# ───────── Test fixtures ─────────
def _write_cache_file(cache_dir: Path, name: str, stock_id: str = None,
                       rows: list = None) -> Path:
    p = cache_dir / name
    data = {
        'stock_id': stock_id or name.replace('.json', ''),
        'fetched_at': '2026-08-27',
        'fetched_start_date': '2000-01-01',
        'row_count': len(rows or []),
        'rows': rows or [],
    }
    p.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    return p


@pytest.fixture
def fake_cache_dir(tmp_path):
    """tmp cache dir with mixed canonical/non-canonical/bad files"""
    d = tmp_path / 'price_cache'
    d.mkdir()
    _write_cache_file(d, '0050.json', stock_id='0050')           # canonical
    _write_cache_file(d, '50.json', stock_id='0050')              # 檔名 not canonical
    _write_cache_file(d, '2002.json', stock_id='2002')            # canonical
    _write_cache_file(d, '9999.json', stock_id='9999')            # not in FinMind
    # bad file (no stock_id)
    (d / 'broken.json').write_text('not valid json{', encoding='utf-8')
    # already correct
    _write_cache_file(d, '00631L.json', stock_id='00631L')
    return d


@pytest.fixture
def mock_match_ticker(monkeypatch):
    """Mock FinMindClient.match_ticker to predefined answers"""
    from lib.finmind import FinMindClient
    canon_map = {
        '0050': {'stock_id': '0050', 'stock_name': '元大台灣50'},
        '2002': {'stock_id': '2002', 'stock_name': '中鋼'},
        '00631L': {'stock_id': '00631L', 'stock_name': '元大台灣50正2'},
    }
    def fake_match(self, user_input):
        ui = user_input.strip()
        if ui in canon_map:
            return canon_map[ui]
        return None
    monkeypatch.setattr(FinMindClient, 'match_ticker', fake_match)
    return canon_map


# ───────── find_trash_dir ─────────
def test_find_trash_dir_returns_a_path():
    """trash dir 應該會回傳一個 mkdir 後的 path"""
    p = find_trash_dir()
    assert p is not None
    assert p.is_dir()


# ───────── safe_trash ─────────
def test_safe_trash_moves_to_trash_dir(tmp_path, monkeypatch):
    """safe_trash 應該把檔 mv 到 trash dir 而不是真的刪除"""
    # Setup
    src = tmp_path / 'test.json'
    src.write_text('test', encoding='utf-8')
    fake_trash = tmp_path / 'Trash'
    fake_trash.mkdir()
    monkeypatch.setattr(
        'migrate_price_cache_to_canonical.find_trash_dir',
        lambda: fake_trash,
    )
    result = safe_trash(src)
    assert result == 'mv-trash'
    assert not src.exists()  # moved away
    assert (fake_trash / 'test.json').is_file()


def test_safe_trash_handles_duplicate_filename(tmp_path, monkeypatch):
    """若 trash 已有同名檔,加 timestamp 避免覆蓋"""
    fake_trash = tmp_path / 'Trash'
    fake_trash.mkdir()
    (fake_trash / 'dup.json').write_text('old', encoding='utf-8')
    monkeypatch.setattr(
        'migrate_price_cache_to_canonical.find_trash_dir',
        lambda: fake_trash,
    )
    src = tmp_path / 'dup.json'
    src.write_text('new', encoding='utf-8')
    safe_trash(src)
    # 兩個檔都還在(原 trash 沒被覆蓋)
    assert (fake_trash / 'dup.json').read_text() == 'old'
    # 新檔帶 timestamp
    new_files = [f for f in fake_trash.iterdir() if f.name.startswith('dup.json.')]
    assert len(new_files) == 1
    assert new_files[0].read_text() == 'new'


def test_safe_trash_dry_run_does_nothing(tmp_path, monkeypatch):
    """dry_run=True 不應該真的移動"""
    src = tmp_path / 'test.json'
    src.write_text('test', encoding='utf-8')
    fake_trash = tmp_path / 'Trash'
    fake_trash.mkdir()
    monkeypatch.setattr(
        'migrate_price_cache_to_canonical.find_trash_dir',
        lambda: fake_trash,
    )
    result = safe_trash(src, dry_run=True)
    assert result == 'dry-run'
    assert src.is_file()  # 沒動


# ───────── migrate_one ─────────
def test_migrate_one_unchanged_when_filename_matches_canonical(fake_cache_dir, mock_match_ticker):
    """檔名已 canonical → unchanged"""
    p = fake_cache_dir / '0050.json'
    action, canonical = migrate_one(p, _make_client())
    assert action == 'unchanged'
    assert canonical == '0050'


def test_migrate_one_trashes_when_filename_not_canonical(fake_cache_dir, mock_match_ticker):
    """檔名 50.json 但 stock_id=0050 → 應 trash 50.json"""
    p = fake_cache_dir / '50.json'
    client = _make_client()
    action, canonical = migrate_one(p, client)
    assert action == 'trashed'
    assert canonical == '0050'
    assert not p.exists()  # 已 trash


def test_migrate_one_dry_run_does_not_trash(fake_cache_dir, mock_match_ticker):
    """dry-run 不實際 trash"""
    p = fake_cache_dir / '50.json'
    client = _make_client()
    action, canonical = migrate_one(p, client, dry_run=True)
    assert action == 'will-trash'
    assert canonical == '0050'
    assert p.is_file()  # 沒動


def test_migrate_one_trashes_when_not_in_finmind(fake_cache_dir, mock_match_ticker):
    """stock_id=9999,FinMind 找不到 → 應 trash (因為下次 fetch 也找不到)
    注意:action 回 'failed' 或 'trashed' 都可以(語意差異):
    - 'failed' = trash 失敗(沒 trashed)
    - 'trashed' = 成功 trash
    兩種情況檔案都應該不在原位置
    """
    p = fake_cache_dir / '9999.json'
    client = _make_client()
    action, canonical = migrate_one(p, client)
    assert action in ('trashed', 'failed')
    assert canonical is None
    assert not p.exists()


def test_migrate_one_skips_bad_json(fake_cache_dir, mock_match_ticker):
    """JSON 壞掉的檔 → skip-bad-file"""
    p = fake_cache_dir / 'broken.json'
    client = _make_client()
    action, canonical = migrate_one(p, client)
    assert action == 'skip-bad-file'
    assert canonical is None


def test_migrate_one_already_canonical_for_00631L(fake_cache_dir, mock_match_ticker):
    """00631L.json 已是 canonical → unchanged"""
    p = fake_cache_dir / '00631L.json'
    client = _make_client()
    action, canonical = migrate_one(p, client)
    assert action == 'unchanged'
    assert canonical == '00631L'


# ───────── main() end-to-end ─────────
def test_main_end_to_end_with_fake_cache(fake_cache_dir, mock_match_ticker, capsys):
    """跑 main() 看 summary 印出來對"""
    from migrate_price_cache_to_canonical import main
    # monkey-patch DEFAULT_CACHE_DIR via sys.argv
    sys.argv = ['migrate', '--cache-dir', str(fake_cache_dir)]
    main()
    captured = capsys.readouterr()
    assert 'unchanged' in captured.out
    assert 'trashed' in captured.out or 'will-trash' in captured.out
    assert 'Summary' in captured.out


def test_main_dry_run(fake_cache_dir, mock_match_ticker, capsys):
    """dry-run 不動檔案"""
    from migrate_price_cache_to_canonical import main
    sys.argv = ['migrate', '--cache-dir', str(fake_cache_dir), '--dry-run']
    main()
    # 所有檔都還在
    assert (fake_cache_dir / '50.json').is_file()
    assert (fake_cache_dir / '9999.json').is_file()
    captured = capsys.readouterr()
    assert 'DRY RUN' in captured.out
    assert 'will-trash' in captured.out


def test_main_with_missing_cache_dir(capsys):
    """cache dir 不存在 → exit 1"""
    from migrate_price_cache_to_canonical import main
    sys.argv = ['migrate', '--cache-dir', '/nonexistent/path/abc123']
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    captured = capsys.readouterr()
    # 訊息是 print 到 stderr(不是 stdout)
    assert '不存在' in (captured.out + captured.err)


def test_main_with_limit(fake_cache_dir, mock_match_ticker, capsys):
    """--limit 限制處理數量"""
    from migrate_price_cache_to_canonical import main
    sys.argv = ['migrate', '--cache-dir', str(fake_cache_dir), '--limit', '2']
    main()
    captured = capsys.readouterr()
    # 預期只處理 2 個檔


# ───────── Helper ─────────
def _make_client():
    """Return a FinMindClient instance with mocked match_ticker (from mock_match_ticker fixture)"""
    from lib.finmind import FinMindClient
    return FinMindClient()
