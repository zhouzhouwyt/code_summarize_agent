"""Shared storage preserves repository isolation and existing research history."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest

from open_deep_research.configuration import Configuration
from open_deep_research.storage.database import connect_database
from open_deep_research.repository.index import repository
from open_deep_research.history import service as history
from tests.unit.test_history import Embedder


@pytest.mark.parametrize('history_first', [True, False])
def test_two_tables_multiple_repositories_and_rebuild(tmp_path, monkeypatch, history_first):
    database = tmp_path / 'shared.sqlite3'
    settings = []
    for name in ('one', 'two'):
        root = tmp_path / name
        root.mkdir()
        (root / 'source.py').write_text(f'def {name}(): return 1\n')
        settings.append(Configuration(repository_path=str(root), research_database=str(database)))
    monkeypatch.setattr(history, '_embedder', lambda _: Embedder())
    if not history_first:
        repository(settings[0], build=True)
    record = history._operation(settings[0], 'local', 'save', 'database question', 'brief', 'report')
    for item in settings:
        assert repository(item, build=True).database == database
    (tmp_path / 'one' / 'source.py').write_text('def updated(): return 2\n')
    repository(settings[0], build=True)
    assert repository(settings[0]).resolve_symbol('updated')
    assert repository(settings[1]).resolve_symbol('two')
    hits = history._operation(settings[0], 'local', 'search', 'database question')
    assert len(hits) == 1 and hits[0].id == record and hits[0].report == 'report'
    with closing(sqlite3.connect(database)) as db:
        assert {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")} == {
            'repository_snapshots', 'research_history'}
        assert db.execute('SELECT count(*) FROM repository_snapshots').fetchone()[0] == 2
    assert list(tmp_path.glob('*.sqlite3')) == [database]


def test_existing_history_upgrade_and_missing_ast(tmp_path):
    database = tmp_path / 'legacy.sqlite3'
    with closing(sqlite3.connect(database)) as db:
        db.execute('''CREATE TABLE research_history (
            id TEXT PRIMARY KEY, scope TEXT NOT NULL, question TEXT NOT NULL,
            brief TEXT NOT NULL, report TEXT NOT NULL, created_at TEXT NOT NULL,
            model_identity TEXT NOT NULL, dimension INTEGER NOT NULL, vector TEXT NOT NULL)''')
        db.execute('INSERT INTO research_history VALUES (?,?,?,?,?,?,?,?,?)',
                   ('old', 'local', 'database question', 'brief', 'old report', '2026-09-28',
                    Embedder.identity + ':question-brief-v2', 2, '[1,0]'))
        db.commit()
    root = tmp_path / 'repo'
    root.mkdir()
    (root / 'source.py').write_text('def example(): pass\n')
    settings = Configuration(repository_path=str(root), research_database=str(database))
    with pytest.raises(ValueError, match='missing'):
        repository(settings)
    repository(settings, build=True)
    hits = history.ResearchHistory(database, Embedder()).search('local', 'database question')
    assert hits[0].id == 'old' and hits[0].report == 'old report' and hits[0].metadata == {}
    other = tmp_path / 'other'
    other.mkdir()
    with pytest.raises(ValueError, match='missing'):
        repository(Configuration(repository_path=str(other), research_database=str(database)))


def test_concurrent_initialization(tmp_path):
    database = tmp_path / 'shared.sqlite3'
    def initialize(_):
        with closing(connect_database(database)) as db:
            return db.execute('SELECT count(*) FROM research_history').fetchone()[0]
    with ThreadPoolExecutor(max_workers=4) as executor:
        assert list(executor.map(initialize, range(8))) == [0] * 8


def test_configuration_compatibility_and_environment(monkeypatch):
    monkeypatch.delenv('RESEARCH_DATABASE', raising=False)
    monkeypatch.delenv('HISTORY_DATABASE', raising=False)
    assert Configuration(history_database='old.sqlite3').research_database == 'old.sqlite3'
    config = {'configurable': {'history_database': 'old.sqlite3'}}
    assert Configuration.from_runnable_config(config).research_database == 'old.sqlite3'
    config['configurable']['research_database'] = 'new.sqlite3'
    assert Configuration.from_runnable_config(config).research_database == 'new.sqlite3'
    monkeypatch.setenv('HISTORY_DATABASE', 'legacy-env.sqlite3')
    assert Configuration.from_runnable_config().research_database == 'legacy-env.sqlite3'
    monkeypatch.setenv('RESEARCH_DATABASE', 'shared-env.sqlite3')
    assert Configuration.from_runnable_config(config).research_database == 'shared-env.sqlite3'
