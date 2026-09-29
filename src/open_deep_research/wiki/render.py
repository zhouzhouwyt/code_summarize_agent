"""Export a Wiki as Markdown pages and a complete JSON knowledge graph."""

import hashlib
import html
import json
import os
from pathlib import Path
from uuid import uuid4
from urllib.parse import quote


def page_filename(identity):
    return hashlib.sha256(identity.encode()).hexdigest()[:24] + '.md'


def module_markdown(wiki, identity):
    graph = wiki['graph']
    module, page = graph['modules'][identity], wiki['pages'][identity]
    lines = [f"# {module['path']}", '', f"版本：`{wiki['revision']}`", '',
             f"说明状态：`{page['status']}`", '', graph['limitation'], '', '## 模块说明', '']
    explanation = page.get('explanation')
    if explanation:
        lines += ['以下内容由模型生成，引用已检查存在，语义尚未独立核实。', '', explanation['summary'], '']
        for claim in explanation['claims']:
            citations = [graph['evidence'][i] for i in claim['evidence_ids']]
            refs = ', '.join(f"`{c['path']}:{c['start_line']}-{c['end_line']}`" for c in citations)
            lines += [f"- {claim['text']}（依据：{refs}）"]
        lines += ['', '### 待核实事项', ''] + ['- ' + text for text in explanation['uncertainties']]
    else:
        lines += ['尚无模型解释；以下为 AST 提取的静态结构。']
    lines += ['', '## 符号', '']
    for sid in module['symbols']:
        node = graph['nodes'][sid]
        lines.append(f"- `{node['kind']}` `{node['qualified_name']}` — `{node['path']}:{node['start_line']}-{node['end_line']}`")
    lines += ['', '## 依赖模块', '']
    for edge in module['dependencies']:
        target = graph['modules'][edge['target']]
        lines.append(f"- {edge['relation']} → [{target['path']}]({page_filename(edge['target'])})")
    lines += ['', '## 被哪些模块依赖', '']
    for edge in module['dependents']:
        source = graph['modules'][edge['source']]
        lines.append(f"- [{source['path']}]({page_filename(edge['source'])}) → {edge['relation']}")
    business_ids = {e['source'] for e in graph.get('business_edges', [])
                    if e.get('target') in module['symbols']}
    if business_ids:
        lines += ['', '## 关联业务要求（关联不代表已实现）', '']
        for topic_id in sorted(business_ids):
            topic = graph['business_topics'][topic_id]
            lines.append(f"- [{topic['title']}](../business/{page_filename(topic_id)}) — {topic['status']}")
    lines += ['', f"未解析或有歧义的关系：{module['unresolved_relations']}。", '']
    return '\n'.join(lines)


def business_markdown(wiki, identity):
    graph = wiki['graph']
    topic = graph['business_topics'][identity]
    citation = graph['evidence'][topic['evidence_id']]
    lines = [f"# {topic['title']}", '', f"主题 ID：`{identity}`", '',
             f"类型：`{topic['kind']}`；文档状态：`{topic['status']}`；分析状态：`{topic['analysis_status']}`", '',
             f"Wiki 版本：`{wiki['revision']}`", '',
             '这是 Demo 设计要求或参考资料，不代表功能已实现或测试已通过。', '',
             f"文档依据：`{citation['path']}:{citation['start_line']}-{citation['end_line']}`", '',
             '## 业务要求原文', '', topic['content'], '', '## 规则—代码—测试关联', '']
    for edge in graph['business_edges']:
        if edge['source'] != identity:
            continue
        target = edge.get('target')
        if target in graph['nodes']:
            node = graph['nodes'][target]
            location = f"{node['path']}:{node['start_line']}-{node['end_line']}"
            link = f"[{node['qualified_name']}](../modules/{page_filename(node['path'] + '::@module')})"
            lines.append(f"- {edge['relation']} → {link}（`{location}`；{edge['origin']}，实现待核实）")
        elif target in graph['business_topics']:
            other = graph['business_topics'][target]
            lines.append(f"- RELATES_TO → [{other['title']}]({page_filename(target)})")
        else:
            lines.append(f"- {edge['relation']} → `{edge.get('reference', '')}`：{edge['resolution']}，未确认关联目标。")
    lines += ['', '## 要求与实现的差异分析', '']
    analysis = topic.get('analysis')
    if analysis:
        lines += [f"模型判断：`{analysis['finding']}`（未独立核实）", '', analysis['summary'], '']
        for eid in analysis['evidence_ids']:
            e = graph['evidence'][eid]
            lines.append(f"- 判断引用：`{e['path']}:{e['start_line']}-{e['end_line']}`")
        lines += ['', '待核实：'] + ['- ' + gap for gap in analysis['gaps']]
    else:
        lines += ['尚未进行模型对照分析。已解析的关联只证明文档和源码位置可定位，不能判断业务符合性。']
    lines += ['', '## 如何分析变更影响', '',
              '先读取关联代码和测试，再沿模块依赖和被依赖关系追踪影响；静态依赖只表示候选范围，不保证行为一定受影响。', '']
    return '\n'.join(lines)


def business_diagram(graph):
    """Draw declared and inferred business links without implying verified compliance."""
    selected = [e for e in graph.get('business_edges', []) if e.get('target')][:40]
    identifiers = list(dict.fromkeys([value for edge in selected for value in (edge['source'], edge['target'])]))
    labels = {identity: f'b{n}' for n, identity in enumerate(identifiers)}
    lines = ['```mermaid', 'flowchart LR']
    for identity, label in labels.items():
        if identity in graph['business_topics']:
            topic = graph['business_topics'][identity]
            title = topic['title'] + ' (' + topic['status'] + ')'
        else:
            node = graph['nodes'][identity]
            title = node['path'] + '::' + node['qualified_name']
        lines.append(f'  {label}["{html.escape(title, quote=True)}"]')
    for edge in selected:
        arrow = '-.->' if edge['origin'] == 'model_inferred' else '-->'
        lines.append(f"  {labels[edge['source']]} {arrow}|{edge['relation']}| {labels[edge['target']]}")
    return '\n'.join(lines + ['```'])


def export_wiki(wiki, repository_root, output='.repository-wiki'):
    """Create a fresh export directory, without overwriting previous documents."""
    root = Path(repository_root).resolve(strict=True)
    repo_key = hashlib.sha256(str(root).encode()).hexdigest()[:20]
    destination = Path(output).resolve() / repo_key / (wiki['revision'][:12] + '-' + uuid4().hex[:8])
    destination.mkdir(parents=True, exist_ok=False)
    pages = destination / 'modules'
    pages.mkdir()
    graph = wiki['graph']
    for identity, module in graph['modules'].items():
        source_link = quote(os.path.relpath(root / module['path'], pages).replace('\\', '/'), safe='/.:')
        body = module_markdown(wiki, identity)
        body += f'\n[返回目录](../README.md) · [阅读源码]({source_link})\n'
        (pages / page_filename(identity)).write_text(body, encoding='utf-8')
    business_pages = destination / 'business'
    business_pages.mkdir()
    for identity, topic in graph.get('business_topics', {}).items():
        document_link = quote(os.path.relpath(root / topic['path'], business_pages).replace('\\', '/'), safe='/.:')
        body = business_markdown(wiki, identity) + f'\n[返回目录](../README.md) · [阅读业务文档]({document_link})\n'
        (business_pages / page_filename(identity)).write_text(body, encoding='utf-8')
    lines = ['# 项目 Wiki', '', f'项目：`{root.name}`', '', f"Wiki 版本（源码＋业务文档）：`{wiki['revision']}`", '',
             graph['limitation'], '',
             f"模块 {len(graph['modules'])} 个，符号 {len(graph['nodes'])} 个，静态关系 {len(graph['edges'])} 条。", '',
             '## 业务主题：要求、实现线索与验证依据', '']
    for identity, topic in graph.get('business_topics', {}).items():
        lines.append(f"- [{topic['title']}](business/{page_filename(identity)}) — {topic['status']} / {topic['analysis_status']}")
    if not graph.get('business_topics'):
        lines.append('未配置业务主题；可在 docs/business/ 中添加 Markdown。')
    lines += ['', '关联可定位不等于实现符合要求，模型差异分析也需人工或测试核实。']
    if graph.get('business_topics'):
        lines += ['', '## 业务—代码—测试关系图', '',
                  '实线为文档声明，虚线为模型推测，均不证明业务符合性。最多展示 40 条可定位关系，完整数据见 graph.json。', '',
                  business_diagram(graph)]
    lines += ['', '## 模块目录', '']
    for identity, module in graph['modules'].items():
        lines.append(f"- [{module['path']}](modules/{page_filename(identity)}) — {wiki['pages'][identity]['status']}")
    # Keep the rendered overview readable; graph.json always contains all edges.
    selected = list(graph['modules'])[:80]
    labels = {identity: f'm{n}' for n, identity in enumerate(selected)}
    edges = [edge for edge in graph['module_edges'] if edge['source'] in labels and edge['target'] in labels][:120]
    lines += ['', '## 模块依赖图', '', '最多展示 80 个模块、120 条关系；完整结构见 [graph.json](graph.json)。', '', '```mermaid', 'flowchart LR']
    for identity, label in labels.items():
        name = html.escape(graph['modules'][identity]['path'], quote=True)
        lines.append(f'  {label}["{name}"]')
    for edge in edges:
        lines.append(f"  {labels[edge['source']]} -->|{edge['relation']}| {labels[edge['target']]}")
    lines += ['```', '', '## 解析诊断', '']
    lines += [f"- `{item['path']}`：{item['error']}" for item in graph['diagnostics']] or ['未报告 Python 语法解析错误。']
    (destination / 'README.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    (destination / 'graph.json').write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding='utf-8')
    return destination
