"""Derive navigable module relationships from a versioned AST snapshot."""

import hashlib


LIMITATION = (
    '源码侧仅分析 Python 静态结构；调用、导入和继承的解析可能不完整。'
    '业务主题来自本地文档，其要求和声明关联不代表功能已实现。'
    '动态分派、反射、配置驱动流程不等同于静态边。模型说明是待核实推断。'
)


def extract_graph(snapshot):
    """Keep all AST nodes/edges and aggregate resolved cross-file dependencies."""
    nodes = snapshot['nodes']
    modules = {}
    evidence = {}
    for path, entry in sorted(snapshot['files'].items()):
        module_id = path + '::@module'
        if module_id not in nodes:
            continue
        modules[module_id] = {
            'id': module_id, 'path': path, 'name': nodes[module_id]['name'],
            'symbols': [sid for sid, node in nodes.items() if node['path'] == path],
            'dependencies': [], 'dependents': [], 'unresolved_relations': 0,
        }
        for sid in modules[module_id]['symbols']:
            node = nodes[sid]
            identity = 'symbol:' + hashlib.sha256(sid.encode()).hexdigest()[:20]
            evidence[identity] = {
                'path': path, 'start_line': node['start_line'], 'end_line': node['end_line'],
                'symbol_id': sid, 'file_hash': entry['sha256'],
            }
    edges, dependencies = [], {}
    for number, original in enumerate(snapshot['edges']):
        edge = dict(original, evidence_id=f'edge:{number}')
        edges.append(edge)
        evidence[edge['evidence_id']] = {
            'path': edge['path'], 'start_line': edge['line'], 'end_line': edge['line'],
            'file_hash': snapshot['files'][edge['path']]['sha256'],
        }
        source = nodes[edge['source']]['path'] + '::@module'
        if edge['status'] != 'resolved' or edge.get('target') not in nodes:
            modules[source]['unresolved_relations'] += 1
            continue
        target = nodes[edge['target']]['path'] + '::@module'
        if source == target or edge['relation'] == 'CONTAINS':
            continue
        key = (source, target, edge['relation'])
        dependencies.setdefault(key, []).append(edge['evidence_id'])
    links = []
    for (source, target, relation), citations in sorted(dependencies.items()):
        links.append(dict(source=source, target=target, relation=relation, evidence_ids=citations))
        modules[source]['dependencies'].append(dict(target=target, relation=relation))
        modules[target]['dependents'].append(dict(source=source, relation=relation))
    return {
        'schema': 1, 'revision': snapshot['revision'], 'modules': modules,
        'nodes': nodes, 'edges': edges, 'module_edges': links, 'evidence': evidence,
        'diagnostics': snapshot['diagnostics'], 'limitation': LIMITATION,
    }
