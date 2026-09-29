"""Wiki structure, citations, persistence, fallback and version invalidation."""

import asyncio
import json
import sqlite3
from contextlib import closing

import pytest

from open_deep_research.configuration import Configuration
from open_deep_research.history.service import ResearchHistory
from open_deep_research.repository.index import repository
from open_deep_research.wiki import service
from open_deep_research.wiki.render import export_wiki
from open_deep_research.wiki.tools import wiki_tools
from tests.unit.test_history import Embedder


@pytest.fixture
def settings(tmp_path):
    root = tmp_path / 'project'
    root.mkdir()
    (root / 'base.py').write_text('class Base: pass\ndef helper(): return 1\n')
    (root / 'app.py').write_text('from base import Base, helper\nclass App(Base): pass\ndef run(): return helper()\ndef dynamic(obj): return obj.unknown()\n')
    (root / 'broken.py').write_text('def invalid(\n')
    return Configuration(repository_path=str(root), research_database=str(tmp_path / 'shared.sqlite3'))


def test_static_graph_export_and_two_table_storage(settings, tmp_path):
    history = ResearchHistory(settings.research_database, Embedder())
    record = history.save('local', 'database question', 'brief', 'existing report')
    wiki = asyncio.run(service.build_wiki(settings, use_llm=False))
    graph = wiki['graph']
    assert len(graph['modules']) == 2
    assert {e['relation'] for e in graph['module_edges']} == {'IMPORTS', 'CALLS', 'INHERITS'}
    assert any(e['status'] == 'unresolved' for e in graph['edges'])
    assert graph['diagnostics'][0]['path'] == 'broken.py'
    for edge in graph['module_edges']:
        assert edge['source'] == 'app.py::@module' and edge['target'] == 'base.py::@module'
        assert all(i in graph['evidence'] for i in edge['evidence_ids'])
    assert service.load_wiki(settings) == wiki
    assert history.search('local', 'database question')[0].id == record
    with closing(sqlite3.connect(settings.research_database)) as db:
        assert {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")} == {
            'repository_snapshots', 'research_history'}
    folder = export_wiki(wiki, settings.repository_path, tmp_path / 'exports')
    assert '```mermaid' in (folder / 'README.md').read_text(encoding='utf-8')
    assert json.loads((folder / 'graph.json').read_text(encoding='utf-8')) == graph
    assert len(list((folder / 'modules').glob('*.md'))) == 2
    assert export_wiki(wiki, settings.repository_path, tmp_path / 'exports') != folder


def test_generated_explanations_have_bounded_context_and_known_citations(settings):
    class Model:
        async def ainvoke(self, messages):
            payload = json.loads(messages[-1].content)
            assert len(messages[-1].content) <= settings.wiki_context_chars
            return dict(summary='模块说明', claims=[dict(text='包含 Python 符号',
                        evidence_ids=[next(iter(payload['evidence']))])], uncertainties=['动态调用需要核实'])
    wiki = asyncio.run(service.build_wiki(settings, model=Model()))
    assert all(p['status'] == 'generated_unverified' for p in wiki['pages'].values())
    tools = {t.name: t for t in wiki_tools(settings)}
    listing = tools['list_project_wiki'].invoke({'query': 'app', 'limit': 1})
    assert listing['total'] == 1
    page = tools['read_project_wiki'].invoke({'module_id': 'app.py::@module', 'limit': 30})
    assert len(page['content']) == 30 and page['next_offset'] == 30
    assert page['verified_current_evidence'] is False
    query = tools['query_wiki_graph'].invoke({'module_id': 'base.py::@module', 'direction': 'dependents', 'limit': 1})
    assert len(query['edges']) == 1 and query['next_offset'] == 1 and query['evidence']
    with pytest.raises(ValueError):
        tools['read_project_wiki'].invoke({'module_id': '../other'})


@pytest.mark.parametrize('failure', ['invalid_citation', 'provider_error'])
def test_model_failures_keep_static_graph(settings, failure):
    class Model:
        async def ainvoke(self, messages):
            if failure == 'provider_error':
                raise RuntimeError('provider unavailable')
            return dict(summary='claim', claims=[dict(text='claim', evidence_ids=['invented'])])
    wiki = asyncio.run(service.build_wiki(settings, model=Model()))
    assert len(wiki['graph']['modules']) == 2
    assert all(p['status'] == 'generation_failed' and p['explanation'] is None for p in wiki['pages'].values())


def test_model_budget_and_initialization_failure(settings, monkeypatch):
    settings.wiki_max_modules = 1
    class Model:
        async def ainvoke(self, messages):
            return dict(summary='Description', claims=[], uncertainties=[])
    wiki = asyncio.run(service.build_wiki(settings, model=Model()))
    assert [p['status'] for p in wiki['pages'].values()] == ['generated_unverified', 'skipped_budget']
    def fail(*args):
        raise RuntimeError('No provider')
    monkeypatch.setattr(service, '_model', fail)
    wiki = asyncio.run(service.build_wiki(settings))
    assert all(p['status'] == 'generation_failed' for p in wiki['pages'].values())


def test_missing_stale_disabled_and_ast_rebuild(settings):
    assert wiki_tools(settings) == []
    asyncio.run(service.build_wiki(settings, use_llm=False))
    tools = wiki_tools(settings)
    assert len(tools) == 3
    settings.wiki_enabled = False
    assert wiki_tools(settings) == []
    settings.wiki_enabled = True
    repository(settings, build=True)
    with pytest.raises(ValueError, match='Wiki missing'):
        service.load_wiki(settings)
    asyncio.run(service.build_wiki(settings, use_llm=False))
    from pathlib import Path
    (Path(settings.repository_path) / 'app.py').write_text('def changed(): pass\n')
    assert wiki_tools(settings) == []
    with pytest.raises(ValueError, match='changed'):
        tools[0].invoke({})


def test_repository_change_during_model_generation_is_not_saved(settings):
    class Model:
        async def ainvoke(self, messages):
            from pathlib import Path
            (Path(settings.repository_path) / 'base.py').write_text('changed = True\n')
            return dict(summary='outdated')
    with pytest.raises(ValueError, match='changed'):
        asyncio.run(service.build_wiki(settings, model=Model()))


def test_prompt_budget_handles_long_escaped_source(settings):
    from pathlib import Path
    from open_deep_research.wiki.graph import extract_graph
    (Path(settings.repository_path) / 'long.py').write_text('value = ' + repr('"\\\n' * 5000))
    snapshot = repository(settings, build=True).data
    graph = extract_graph(snapshot)
    payload = service.module_context(snapshot, graph, graph['modules']['long.py::@module'], 2000)
    assert len(json.dumps(payload, ensure_ascii=False)) <= 2000 and payload['truncated']
