"""Read generated Wiki data as leads, without treating model prose as evidence."""

from langchain_core.tools import tool

from open_deep_research.wiki.render import business_markdown, module_markdown
from open_deep_research.wiki.service import load_wiki


def wiki_tools(settings):
    if not settings.wiki_enabled or not settings.repository_path:
        return []
    try:
        initial = load_wiki(settings)
    except Exception:
        return []

    @tool
    def list_project_wiki(query: str = '', offset: int = 0, limit: int = 20):
        """List Wiki module IDs by path/name; generated descriptions are unverified leads."""
        if offset < 0 or not 1 <= limit <= 50:
            raise ValueError('Invalid pagination')
        wiki = load_wiki(settings)
        modules = [dict(id=m['id'], path=m['path'], status=wiki['pages'][m['id']]['status'])
                   for m in wiki['graph']['modules'].values()
                   if query.casefold() in (m['path'] + ' ' + m['name']).casefold()]
        return dict(revision=wiki['revision'], modules=modules[offset:offset+limit], total=len(modules),
                    next_offset=offset+limit if offset+limit < len(modules) else None)

    @tool
    def read_project_wiki(module_id: str, offset: int = 0, limit: int = 6000):
        """Read a Wiki page by module ID; independently verify its claims with source tools."""
        if offset < 0 or not 1 <= limit <= 12000:
            raise ValueError('Invalid pagination')
        wiki = load_wiki(settings)
        if module_id not in wiki['pages']:
            raise ValueError('Unknown Wiki module')
        content = module_markdown(wiki, module_id)
        return dict(revision=wiki['revision'], content=content[offset:offset+limit],
                    next_offset=offset+limit if offset+limit < len(content) else None,
                    verified_current_evidence=False)

    @tool
    def query_wiki_graph(module_id: str, direction: str = 'dependencies', offset: int = 0, limit: int = 30):
        """Inspect direct module dependencies or dependents with AST source citations."""
        if direction not in {'dependencies', 'dependents'} or offset < 0 or not 1 <= limit <= 50:
            raise ValueError('Invalid direction or pagination')
        wiki = load_wiki(settings)
        graph = wiki['graph']
        if module_id not in graph['modules']:
            raise ValueError('Unknown Wiki module')
        key = 'source' if direction == 'dependencies' else 'target'
        edges = [e for e in graph['module_edges'] if e[key] == module_id]
        selected = edges[offset:offset+limit]
        # A heavily reused dependency can have many source citations; cap each response.
        result = [{**e, 'evidence_ids': e['evidence_ids'][:5],
                   'citations_truncated': len(e['evidence_ids']) > 5} for e in selected]
        evidence = {i: graph['evidence'][i] for e in result for i in e['evidence_ids']}
        return dict(revision=wiki['revision'], edges=result, evidence=evidence,
                    next_offset=offset+limit if offset+limit < len(edges) else None,
                    limitation=graph['limitation'])

    @tool
    def list_business_topics(query: str = '', offset: int = 0, limit: int = 20):
        """Find business requirements, processes or planned changes; these are not implementation facts."""
        if offset < 0 or not 1 <= limit <= 50:
            raise ValueError('Invalid pagination')
        wiki = load_wiki(settings)
        topics = [dict(id=t['id'], title=t['title'], kind=t['kind'], status=t['status'], path=t['path'])
                  for t in wiki['graph']['business_topics'].values()
                  if query.casefold() in (t['title'] + ' ' + t['content']).casefold()]
        return dict(revision=wiki['revision'], topics=topics[offset:offset+limit], total=len(topics),
                    next_offset=offset+limit if offset+limit < len(topics) else None)

    @tool
    def read_business_topic(topic_id: str, offset: int = 0, limit: int = 6000):
        """Read a business rule with document/code/test references and unverified discrepancy analysis."""
        if offset < 0 or not 1 <= limit <= 12000:
            raise ValueError('Invalid pagination')
        wiki = load_wiki(settings)
        if topic_id not in wiki['graph']['business_topics']:
            raise ValueError('Unknown business topic')
        content = business_markdown(wiki, topic_id)
        return dict(revision=wiki['revision'], content=content[offset:offset+limit],
                    next_offset=offset+limit if offset+limit < len(content) else None,
                    verified_current_evidence=False)

    @tool
    def query_business_graph(topic_id: str, offset: int = 0, limit: int = 20):
        """Trace a business topic to declared/inferred code and tests plus candidate module impacts.
        Presence of a code/test link does not prove compliance or a passing test."""
        if offset < 0 or not 1 <= limit <= 50:
            raise ValueError('Invalid pagination')
        wiki = load_wiki(settings)
        graph = wiki['graph']
        if topic_id not in graph['business_topics']:
            raise ValueError('Unknown business topic')
        edges = [e for e in graph['business_edges'] if e['source'] == topic_id or e.get('target') == topic_id]
        selected = edges[offset:offset+limit]
        modules = {graph['nodes'][e['target']]['path'] + '::@module'
                   for e in selected if e.get('target') in graph['nodes']}
        impacts = [e for e in graph['module_edges'] if e['source'] in modules or e['target'] in modules]
        impacts_bounded = [{**e, 'evidence_ids': e['evidence_ids'][:5],
                            'citations_truncated': len(e['evidence_ids']) > 5} for e in impacts[:10]]
        evidence = {i: graph['evidence'][i] for e in selected + impacts_bounded for i in e['evidence_ids']}
        return dict(revision=wiki['revision'], edges=selected, evidence=evidence,
                    candidate_module_impacts=impacts_bounded, impacts_truncated=len(impacts) > 10,
                    next_offset=offset+limit if offset+limit < len(edges) else None,
                    verified_implementation=False,
                    limitation='文档声明和模型推测均不证明实现符合规则；模块依赖仅作为变更影响线索。')

    tools = [list_project_wiki, read_project_wiki, query_wiki_graph]
    if initial['graph'].get('business_topics'):
        tools += [list_business_topics, read_business_topic, query_business_graph]
    return tools
