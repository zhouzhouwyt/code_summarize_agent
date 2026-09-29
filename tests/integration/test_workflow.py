"""Tests for supervised code research with optional indexes and explicit history reuse."""
import asyncio
import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from open_deep_research.configuration import Configuration
from open_deep_research.repository.index import RepositoryKnowledge, repository
from open_deep_research.repository.tools import code_tools, fingerprint
from open_deep_research.workflow.state import ClarifyWithUser, ResearchQuestion, ResearchResult
from open_deep_research.history import service as history


class Embedder:
    identity = 'test-history'
    dimension = 2
    def windows(self, text):
        yield 0, len(text)
    def encode(self, texts):
        return [[1, 0] for text in texts]


@pytest.fixture
def project(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    (root / 'stock.py').write_text('def deduct():\n    return 1\n', encoding='utf-8')
    (root / 'orders.py').write_text('''from stock import deduct as reserve
class Base:
    pass
class Service(Base):
    def run(self):
        return self.dynamic()
def create_order():
    return reserve()
def caller():
    return create_order()
def shadow(reserve):
    return reserve()
''', encoding='utf-8')
    return root


def config_for(project, tmp_path):
    return {'configurable': {'repository_path': str(project),
            'research_database': str(tmp_path/'research.sqlite3'), 'allow_clarification': False}}


def test_static_graph_and_stale_index(project, tmp_path):
    settings = Configuration(**config_for(project, tmp_path)['configurable'])
    store = repository(settings, build=True)
    deduct = store.resolve_symbol('deduct')[0]['id']
    assert len(store.graph(deduct, 'callers')['edges']) == 1
    assert len(store.graph(deduct, 'callers', 2)['edges']) == 2
    assert store.graph(deduct, 'callers')['unresolved_in_repository'] >= 2
    base = store.resolve_symbol('Base')[0]['id']
    assert len(store.graph(base, 'implementations')['edges']) == 1
    assert 'return reserve()' in store.read_symbol(store.resolve_symbol('create_order')[0]['id'])['content']
    (project/'other.py').write_text('def create_order(): return 2\n')
    with pytest.raises(ValueError, match='changed'):
        store.load()
    assert {t.name for t in code_tools(settings)} == {'list_repository_files','search_repository','read_repository_file'}
    store.build()
    assert len(store.resolve_symbol('create_order')) == 2
    assert 'entry_vectors' not in store.data and 'modules' not in store.data


def test_no_index_tools_path_limits_and_version_change(project, tmp_path):
    settings = Configuration(**config_for(project, tmp_path)['configurable'])
    revision, hashes = fingerprint(project)
    tools = {t.name:t for t in code_tools(settings, {'revision':revision,'file_hashes':hashes})}
    assert not (tmp_path/'research.sqlite3').exists()
    assert tools['search_repository'].invoke({'query':'reserve'})['hits']
    evidence = tools['read_repository_file'].invoke({'path':'orders.py','end_line':3})
    assert evidence['next_line'] == 4 and evidence['evidence_id']
    with pytest.raises((ValueError, FileNotFoundError)):
        tools['read_repository_file'].invoke({'path':'../outside.py'})
    (project/'.env').write_text('SECRET=hidden')
    assert '.env' not in tools['list_repository_files'].invoke({})['paths']
    (project/'orders.py').write_text('changed')
    with pytest.raises(ValueError, match='changed'):
        tools['read_repository_file'].invoke({'path':'orders.py'})


@pytest.mark.parametrize('index_mode', ['missing', 'ready', 'stale', 'version_unknown'])
def test_entire_graph_history_reaches_researcher_and_writer(project, tmp_path, monkeypatch, index_mode):
    from open_deep_research.workflow import graph
    from open_deep_research.workflow import context as code_workflow
    config = config_for(project, tmp_path)
    settings = Configuration(**config['configurable'])
    if index_mode in {'ready', 'stale'}:
        repository(settings, build=True)
    if index_mode == 'stale':
        (project/'stock.py').write_text('def deduct(): return 2\n')
    revision, _ = fingerprint(project)
    if index_mode == 'version_unknown':
        def unavailable(*args):
            raise OSError('version scan unavailable')
        monkeypatch.setattr(code_workflow, 'fingerprint', unavailable)
    monkeypatch.setattr(history, '_embedder', lambda model: Embedder())
    store = history.ResearchHistory(settings.history_database, Embedder())
    record = store.save(history._scope(config,settings), 'How are orders created?', 'Trace orders',
                        'OLD_LEAD: inspect orders.py create_order and reserve.', {'revision':revision})
    stages, researcher_prompts, writer_prompts = [], [], []
    class Model:
        def __init__(self, schema=None, role='writer'):
            self.schema, self.role = schema, role
        def with_structured_output(self,schema): return Model(schema)
        def with_config(self,*args,**kwargs): return self
        def with_retry(self,**kwargs): return self
        def bind_tools(self,tools):
            names = {getattr(t,'name',getattr(t,'__name__','')) for t in tools}
            return Model(role='supervisor' if 'ConductResearch' in names else 'researcher')
        async def ainvoke(self,messages):
            if self.schema is ResearchQuestion:
                stages.append('brief')
                return ResearchQuestion(research_brief='Trace order creation and verify OLD_LEAD')
            if self.schema is ResearchResult:
                stages.append('compress')
                receipt = next(json.loads(m.content) for m in messages if m.type=='tool' and m.name=='read_repository_file')
                return ResearchResult(summary='create_order calls reserve [orders.py:7-8]',status='completed',
                    history_assessments=[{'history_id':record,'claim':'create_order calls reserve','status':'verified',
                    'explanation':'Read current code','evidence_ids':[receipt['evidence_id']]}])
            if self.role=='supervisor':
                stages.append('supervisor')
                if not any(m.type=='tool' for m in messages):
                    assert any('OLD_LEAD' in str(m.content) for m in messages)
                    return AIMessage(content='',tool_calls=[{'id':'delegate','name':'ConductResearch',
                       'args':{'research_topic':'Read order entry', 'history_ids':[record], 'verification_targets':['Verify reserve call']}}])
                return AIMessage(content='',tool_calls=[{'id':'done','name':'ResearchComplete','args':{}}])
            if self.role=='researcher':
                researcher_prompts.extend(messages)
                stages.append('researcher')
                if not any(m.type=='tool' for m in messages):
                    return AIMessage(content='',tool_calls=[{'id':'read','name':'read_repository_file','args':{'path':'orders.py'}}])
                return AIMessage(content='',tool_calls=[{'id':'finished','name':'ResearchComplete','args':{}}])
            stages.append('writer')
            writer_prompts.extend(messages)
            return AIMessage(content='Verified reserve call [orders.py:7-8].')
    monkeypatch.setattr(graph,'configurable_model',Model())
    result = asyncio.run(graph.deep_researcher.ainvoke({'messages':[HumanMessage(content='How are orders created?')]},config))
    assert stages == ['brief','supervisor','researcher','researcher','compress','supervisor','writer']
    assert result['report_succeeded'] and result['history_save_status']=='saved'
    assert result['research_status']=='completed'
    assert result['research_results'][0]['history_assessments'][0]['status']=='verified'
    assert any('OLD_LEAD' in str(m.content) for m in researcher_prompts)
    assert any('verified' in str(m.content) and record in str(m.content) for m in writer_prompts)
    assert result['repository_context']['index_status'] == ('ready' if index_mode=='ready' else 'unavailable')
    assert bool(result['repository_revision']) == (index_mode!='version_unknown')
    history_hit = store.search(history._scope(config,settings),'orders', revision=result['repository_revision'] or None)
    assert any(h.metadata.get('research_results') for h in history_hit)


def test_missing_path_and_clarification_stop_without_supervisor(project,tmp_path,monkeypatch):
    from open_deep_research.workflow import graph
    class Model:
        def with_structured_output(self,schema):
            assert schema is ClarifyWithUser
            return self
        def with_retry(self,**kwargs): return self
        def with_config(self,*args,**kwargs): return self
        async def ainvoke(self,messages):
            return ClarifyWithUser(need_clarification=True,question='Which flow?',verification='')
    monkeypatch.setattr(graph,'configurable_model',Model())
    missing = asyncio.run(graph.deep_researcher.ainvoke({'messages':[HumanMessage(content='q')]},{}))
    assert not missing['report_succeeded'] and 'repository_path' in missing['messages'][-1].content
    config=config_for(project,tmp_path)
    config['configurable']['allow_clarification']=True
    result=asyncio.run(graph.deep_researcher.ainvoke({'messages':[HumanMessage(content='q')]},config))
    assert result['messages'][-1].content=='Which flow?'
    assert not Path(config['configurable']['research_database']).exists()


def test_optional_web_and_mcp_are_composed(project,tmp_path,monkeypatch):
    from open_deep_research.integrations import tools as utils
    from langchain_core.tools import tool
    @tool
    def fake_web(query:str):
        """Test web tool."""
        return query
    @tool
    def fake_mcp(query:str):
        """Test MCP tool."""
        return query
    async def web(*args): return [fake_web]
    async def mcp(*args): return [fake_mcp]
    monkeypatch.setattr(utils,'get_search_tool',web)
    monkeypatch.setattr(utils,'load_mcp_tools',mcp)
    config=config_for(project,tmp_path)
    config['configurable'].update(repository_allow_web=True,mcp_config={'url':'http://example.test','tools':['fake_mcp']})
    names={t.name for t in asyncio.run(utils.get_all_tools(config))}
    assert {'fake_web','fake_mcp','read_repository_file','think_tool','ResearchComplete'} <= names


def test_history_version_scope_and_paged_read(project,tmp_path):
    config=config_for(project,tmp_path)
    settings=Configuration(**config['configurable'])
    store=history.ResearchHistory(settings.history_database,Embedder())
    scope=history._scope(config,settings)
    old=store.save(scope,'orders','brief','old report',{'revision':'old'})
    new=store.save(scope,'orders','brief','new report',{'revision':'new'})
    assert [h.id for h in store.search(scope,'orders',revision='new')]==[new]
    assert len(store.search(scope,'orders'))==2
    reader=history.history_tools(config,[{'id':new}])[0]
    result=reader.invoke({'record_id':new,'limit':3})
    assert result['report_excerpt']=='new' and result['next_offset']==3
    with pytest.raises(ValueError): reader.invoke({'record_id':old})


def test_history_unavailable_does_not_block_supervisor(project,tmp_path,monkeypatch):
    from open_deep_research.workflow import graph
    def unavailable(*args): raise RuntimeError('embedding unavailable')
    monkeypatch.setattr(history,'_operation',unavailable)
    calls=[]
    class Model:
        def __init__(self,schema=None): self.schema=schema
        def with_structured_output(self,schema): return Model(schema)
        def with_retry(self,**kwargs): return self
        def with_config(self,*args,**kwargs): return self
        def bind_tools(self,*args,**kwargs): calls.append('supervisor');return self
        async def ainvoke(self,messages):
            if self.schema is ResearchQuestion:return ResearchQuestion(research_brief='Inspect orders')
            return AIMessage(content='Insufficient evidence; source still needs reading.')
    monkeypatch.setattr(graph,'configurable_model',Model())
    result=asyncio.run(graph.deep_researcher.ainvoke({'messages':[HumanMessage(content='orders')]},config_for(project,tmp_path)))
    assert calls==['supervisor']
    assert result['history_status']=='retrieval_error'
    assert result['history_save_status']=='save_error'
    assert result['research_status']=='partial' and result['final_report']


def test_budget_and_fabricated_history_evidence_stay_unverified(monkeypatch):
    from open_deep_research.workflow import graph
    class Model:
        def with_structured_output(self,*args):return self
        def with_config(self,*args,**kwargs):return self
        async def ainvoke(self,messages):
            return ResearchResult(summary='Claim',status='completed',history_assessments=[{
                'history_id':'h','claim':'claim','status':'verified','explanation':'claimed', 'evidence_ids':['invented']}])
    monkeypatch.setattr(graph,'configurable_model',Model())
    state={'researcher_messages':[HumanMessage(content='task')], 'history_matches':[{'id':'h'},{'id':'h2'}],
           'history_context':'[]','source_evidence':[], 'termination_reason':'budget_exhausted'}
    result=asyncio.run(graph.compress_research(state,{}))['research_result']
    assert result['status']=='partial'
    assert len(result['history_assessments'])==2
    assert all(a['status']=='unverified' for a in result['history_assessments'])


def test_run_reset_and_repository_change_prevent_mixed_reports(project,tmp_path):
    from open_deep_research.workflow.context import validate_repository
    from open_deep_research.workflow.graph import final_report_generation
    config=config_for(project,tmp_path)
    state={'final_report':'old','last_completed_report':'old','research_results':[{'status':'completed'}]}
    reset=asyncio.run(validate_repository(state,config)).update
    assert reset['final_report']=='' and reset['research_results']['value']==[]
    revision,_=fingerprint(project)
    (project/'stock.py').write_text('changed')
    result=asyncio.run(final_report_generation({'notes':[], 'repository_context':{'root':str(project),'revision':revision}},config))
    assert not result['report_succeeded'] and result['final_report']==''


def test_parallel_children_keep_their_own_history(project,tmp_path,monkeypatch):
    from open_deep_research.workflow import graph
    captured=[]
    class Child:
        async def ainvoke(self,state,config):
            captured.append(state)
            await asyncio.sleep(0)
            return {'compressed_research':'done','research_result':{'status':'completed'},'raw_notes':[]}
    monkeypatch.setattr(graph,'researcher_subgraph',Child())
    state={'supervisor_messages':[AIMessage(content='',tool_calls=[
        {'id':'a','name':'ConductResearch','args':{'research_topic':'A','history_ids':['h1']}},
        {'id':'b','name':'ConductResearch','args':{'research_topic':'B','history_ids':['h2']}}])],
        'history_context':json.dumps([{'id':'h1','report_excerpt':'first'},{'id':'h2','report_excerpt':'second'}]),
        'history_matches':[{'id':'h1'},{'id':'h2'}], 'repository_context':{}, 'research_iterations':1}
    command=asyncio.run(graph.supervisor_tools(state,config_for(project,tmp_path)))
    assert command.goto=='supervisor' and len(command.update['research_results'])==2
    assert json.loads(captured[0]['history_context'])==[{'id':'h1','report_excerpt':'first'}]
    assert json.loads(captured[1]['history_context'])==[{'id':'h2','report_excerpt':'second'}]


def test_checkpointed_second_question_does_not_reuse_previous_results(project,tmp_path,monkeypatch):
    from langgraph.checkpoint.memory import InMemorySaver
    from open_deep_research.workflow import graph
    calls=[]
    class Model:
        def __init__(self,schema=None):self.schema=schema
        def with_structured_output(self,schema):return Model(schema)
        def with_retry(self,**kwargs):return self
        def with_config(self,*args,**kwargs):return self
        def bind_tools(self,*args,**kwargs):return self
        async def ainvoke(self,messages):
            if self.schema is ResearchQuestion:return ResearchQuestion(research_brief='Current task')
            calls.append(messages)
            return AIMessage(content='No verified source evidence available.')
    monkeypatch.setattr(graph,'configurable_model',Model())
    config=config_for(project,tmp_path)
    config['configurable'].update(history_enabled=False,thread_id='two-turns')
    workflow=graph.deep_researcher_builder.compile(checkpointer=InMemorySaver())
    async def run():
        first=await workflow.ainvoke({'messages':[HumanMessage(content='first question')]},config)
        second=await workflow.ainvoke({'messages':[HumanMessage(content='second question')]},config)
        assert first['history_question']=='first question'
        assert second['history_question']=='second question'
        assert second['research_results']==[] and second['research_iterations']==1
    asyncio.run(run())


def test_clarifier_and_brief_receive_validated_repository(project,tmp_path,monkeypatch):
    from open_deep_research.workflow import graph
    from open_deep_research.workflow.context import validate_repository
    captured=[]
    class Model:
        def __init__(self,schema=None):self.schema=schema
        def with_structured_output(self,schema):return Model(schema)
        def with_retry(self,**kwargs):return self
        def with_config(self,*args,**kwargs):return self
        async def ainvoke(self,messages):
            # Both LLM stages must see the selected repo independently of user text.
            system=next(m.content for m in messages if m.type=='system')
            context=json.loads(system.split('Repository context: ',1)[1])
            assert Path(context['root'])==project.resolve()
            captured.append(self.schema)
            if self.schema is ClarifyWithUser:
                assert 'entry points themselves' in system
                return ClarifyWithUser(need_clarification=False,question='',verification='开始研究')
            return ResearchQuestion(research_brief='Trace report saving in the configured repository')
    monkeypatch.setattr(graph,'configurable_model',Model())
    config=config_for(project,tmp_path)
    config['configurable']['allow_clarification']=True
    state={'messages':[HumanMessage(content='请分析历史报告保存的调用流程，引用对应源码。')]}
    async def run():
        state.update((await validate_repository(state,config)).update)
        command=await graph.clarify_with_user(state,config)
        assert command.goto=='write_research_brief'
        brief=await graph.write_research_brief(state,config)
        assert brief.goto=='prepare_repository_context'
    asyncio.run(run())
    assert captured==[ClarifyWithUser,ResearchQuestion]
