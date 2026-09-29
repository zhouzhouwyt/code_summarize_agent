"""Business rules, declared/inferred mappings and document-aware Wiki versions."""

import asyncio
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from open_deep_research.configuration import Configuration
from open_deep_research.history.service import ResearchHistory
from open_deep_research.integrations.tools import get_all_tools
from open_deep_research.wiki import service
from open_deep_research.wiki.business import sections, read_business_documents, business_context
from open_deep_research.wiki.render import export_wiki, page_filename
from open_deep_research.wiki.tools import wiki_tools
from tests.unit.test_history import Embedder


def document():
    return '''# Demo rules
## Evidence requirement
<!-- wiki: {"id":"evidence","kind":"rule","status":"required","code_refs":["app.py::answer","app.py::missing"],"test_refs":["test_app.py::test_answer"],"related":["planned"]} -->
The answer must cite current evidence. Inspect answer before changing history behavior.
## Future behavior
<!-- wiki: {"id":"planned","kind":"change","status":"planned"} -->
This is a plan, not an implemented guarantee.
'''


@pytest.fixture
def settings(tmp_path):
    root = tmp_path / 'project'
    (root / 'docs/business').mkdir(parents=True)
    (root / 'app.py').write_text('def answer(): return "no citation"\n')
    (root / 'test_app.py').write_text('from app import answer\ndef test_answer(): assert answer()\n')
    (root / 'docs/business/rules.md').write_text(document(), encoding='utf-8')
    return Configuration(repository_path=str(root), research_database=str(tmp_path / 'shared.sqlite3'))


def test_requirements_link_to_code_and_tests_without_claiming_compliance(settings, tmp_path):
    history = ResearchHistory(settings.research_database, Embedder())
    record = history.save('local', 'database', 'brief', 'saved report')
    wiki = asyncio.run(service.build_wiki(settings, use_llm=False))
    graph = wiki['graph']
    topic = graph['business_topics']['business:evidence']
    assert graph['business_topics']['business:planned']['status'] == 'planned'
    citation = graph['evidence'][topic['evidence_id']]
    assert citation['path'] == 'docs/business/rules.md' and citation['start_line'] == 2
    edges = graph['business_edges']
    assert any(e['relation'] == 'HAS_TEST' and e['resolution'] == 'resolved' for e in edges)
    assert any(e.get('reference') == 'app.py::missing' and e['resolution'] == 'missing' for e in edges)
    assert all(e['verified_implementation'] is False for e in edges)
    assert history.search('local', 'database')[0].id == record
    with closing(sqlite3.connect(settings.research_database)) as db:
        assert db.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0] == 2
    folder = export_wiki(wiki, settings.repository_path, tmp_path / 'exports')
    page = folder / 'business' / page_filename('business:evidence')
    content = page.read_text(encoding='utf-8')
    assert 'app.py::missing' in content and '尚未进行模型对照分析' in content
    assert (folder / 'modules' / page_filename('app.py::@module')).is_file()
    assert 'Evidence requirement' in (folder / 'README.md').read_text(encoding='utf-8')


@pytest.mark.parametrize('change', ['edit', 'add', 'delete', 'directory'])
def test_document_changes_invalidate_previously_created_tools(settings, change):
    wiki = asyncio.run(service.build_wiki(settings, use_llm=False))
    tools = {t.name: t for t in wiki_tools(settings)}
    root = Path(settings.repository_path)
    if change == 'edit':
        (root / 'docs/business/rules.md').write_text(document() + '\nChanged requirement.\n')
    elif change == 'add':
        (root / 'docs/business/new.md').write_text('# Newly added document\nNew knowledge.')
    elif change == 'delete':
        (root / 'docs/business/rules.md').unlink()
    else:
        settings.wiki_business_dir = 'docs/other'
    with pytest.raises(ValueError, match='documents changed'):
        tools['list_business_topics'].invoke({})
    assert wiki_tools(settings) == []
    rebuilt = asyncio.run(service.build_wiki(settings, use_llm=False))
    assert rebuilt['source_revision'] == wiki['source_revision'] and rebuilt['revision'] != wiki['revision']


def test_business_tools_are_available_to_research_and_paginated(settings):
    asyncio.run(service.build_wiki(settings, use_llm=False))
    config = {'configurable': settings.model_dump()}
    tools = {t.name: t for t in asyncio.run(get_all_tools(config))}
    topics = tools['list_business_topics'].invoke({'query': 'evidence', 'limit': 1})
    assert topics['topics'][0]['id'] == 'business:evidence'
    page = tools['read_business_topic'].invoke({'topic_id': 'business:evidence', 'limit': 80})
    assert len(page['content']) == 80 and page['next_offset'] == 80
    assert page['verified_current_evidence'] is False
    result = tools['query_business_graph'].invoke({'topic_id': 'business:evidence', 'limit': 1})
    assert len(result['edges']) == 1 and result['next_offset'] == 1
    assert result['candidate_module_impacts'] and result['evidence']
    with pytest.raises(ValueError):
        tools['read_business_topic'].invoke({'topic_id': '../private'})


class ModuleModel:
    async def ainvoke(self, messages):
        return {'summary': 'module', 'claims': []}


class BusinessModel:
    async def ainvoke(self, messages):
        payload = json.loads(messages[-1].content)
        docs = [i for i, e in payload['evidence'].items() if e.get('kind') == 'document']
        code = [i for i, e in payload['evidence'].items() if e.get('symbol_id')]
        if not code:
            return {'summary': 'No implementation evidence', 'finding': 'unknown', 'gaps': ['Need source']}
        sid = payload['evidence'][code[0]]['symbol_id']
        return {'summary': 'The implementation may omit citations.', 'finding': 'potential_conflict',
                'evidence_ids': docs + code[:1], 'suggested_links': [
                    {'symbol_id': sid, 'reason': 'Candidate implementation', 'evidence_ids': docs + code[:1]}]}


def test_model_comparison_keeps_both_evidence_types_and_marks_inference(settings):
    wiki = asyncio.run(service.build_wiki(settings, model=ModuleModel(), business_model=BusinessModel()))
    graph = wiki['graph']
    topic = graph['business_topics']['business:evidence']
    assert topic['analysis_status'] == 'generated_unverified'
    assert topic['analysis']['finding'] == 'potential_conflict'
    inferred = [e for e in graph['business_edges'] if e['origin'] == 'model_inferred']
    assert inferred and all(e['verified_implementation'] is False for e in inferred)


@pytest.mark.parametrize('mode', ['invented_evidence', 'invented_symbol', 'no_document', 'no_code'])
def test_unsupported_model_claims_are_rejected(settings, mode):
    class BadModel(BusinessModel):
        async def ainvoke(self, messages):
            result = await super().ainvoke(messages)
            if result['finding'] == 'unknown':
                return result
            if mode == 'invented_evidence':
                result['evidence_ids'] = ['not-real']
            elif mode == 'invented_symbol':
                result['suggested_links'][0]['symbol_id'] = 'invented'
            elif mode == 'no_document':
                result['evidence_ids'] = result['evidence_ids'][1:]
            else:
                result['evidence_ids'] = result['evidence_ids'][:1]
            return result
    wiki = asyncio.run(service.build_wiki(settings, model=ModuleModel(), business_model=BadModel()))
    topic = wiki['graph']['business_topics']['business:evidence']
    assert topic['analysis_status'] == 'generation_failed' and topic['analysis'] is None
    assert all(e['origin'] != 'model_inferred' for e in wiki['graph']['business_edges'])


def test_mid_generation_document_changes_do_not_persist(settings):
    class ChangingModel(BusinessModel):
        async def ainvoke(self, messages):
            path = Path(settings.repository_path) / 'docs/business/rules.md'
            path.write_text(document() + '\nChanged during generation.')
            return await super().ainvoke(messages)
    with pytest.raises(ValueError, match='documents changed'):
        asyncio.run(service.build_wiki(settings, model=ModuleModel(), business_model=ChangingModel()))


def test_plain_markdown_fences_invalid_metadata_and_path_escape(settings):
    assert len(list(sections('# Title\n## Real\n```python\n## Not a topic\n```\nText'))) == 1
    path = Path(settings.repository_path) / 'docs/business/rules.md'
    path.write_text('# Plain document\nGeneral reference material.\n```markdown\n<!-- wiki: {invalid example} -->\n```')
    wiki = asyncio.run(service.build_wiki(settings, use_llm=False))
    topic = next(iter(wiki['graph']['business_topics'].values()))
    assert topic['status'] == 'reference'
    path.write_text('## Wrong\n<!-- wiki: {invalid} -->')
    with pytest.raises(ValueError, match='Invalid Wiki metadata'):
        asyncio.run(service.build_wiki(settings, use_llm=False))
    with pytest.raises(ValueError, match='inside the repository'):
        read_business_documents(settings.repository_path, '../outside')


def test_context_is_bounded_and_other_docs_do_not_invalidate(settings):
    wiki = asyncio.run(service.build_wiki(settings, use_llm=False))
    from open_deep_research.repository.index import repository
    snapshot = repository(settings).data
    topic = wiki['graph']['business_topics']['business:evidence']
    topic = {**topic, 'content': topic['content'] + '"\\\n' * 5000}
    payload = business_context(snapshot, wiki['graph'], topic, 2000)
    assert payload['truncated'] and len(json.dumps(payload, ensure_ascii=False)) <= 2000
    (Path(settings.repository_path) / 'docs/unrelated.md').write_text('Outside configured business directory')
    assert service.load_wiki(settings)['revision'] == wiki['revision']
