"""Read-only repository tools with output-volume compression.

Designed for small-context models (e.g. free Alibaba Bailian endpoints): every tool
bounds and compacts its return payload while preserving source citations (path /
line / status / revision) so answers stay auditable. Raise the per-call budgets
(line_chars, limit, ...) when a larger context window is available.
"""
import hashlib
import json
import os
import subprocess
from pathlib import Path

from langchain_core.tools import tool
from open_deep_research.repository.index import EXCLUDED, repository

TEXT_SUFFIXES = {'.py', '.pyi', '.md', '.rst', '.txt', '.toml', '.yaml', '.yml', '.json',
                 '.ini', '.cfg', '.java', '.js', '.ts', '.tsx', '.jsx', '.go', '.rs', '.sql',
                 '.html', '.css', '.xml', '.sh', '.ps1', '.c', '.h', '.cpp', '.cs', '.vue'}
EXCLUDED = EXCLUDED | {'.idea', '.langgraph_api', '.benchmarks', '.codex', '.agents'}

# ---- Output-volume budgets (tune to your model's context window) ----
BUDGET = {
    'list_default_limit': 50,         # was 100
    'search_default_limit': 10,       # was 30; cap raised: max 30
    'search_line_chars': 300,         # was 1000 per hit
    'search_per_file': 5,             # max hits kept per file
    'read_max_lines': 100,            # was 300
    'read_char_budget': 10000,        # was 30000
    'read_code_default_chars': 6000,  # was 8000
    'resolve_max_matches': 8,
    'graph_max_edges': 50,            # was 100
    'doc_budget': 300,
    'expr_budget': 200,
}


def _clip(text, limit):
    """Truncate text at `limit` chars with an explicit overflow marker."""
    if text is None:
        return ''
    text = str(text)
    if len(text) <= limit:
        return text
    return text[:limit] + '…[+{} chars]'.format(len(text) - limit)


def _compact_node(node):
    """Return only the audit-relevant fields of an indexed symbol."""
    return {
        'id': node.get('id'),
        'path': node.get('path'),
        'name': node.get('name'),
        'qualified_name': node.get('qualified_name'),
        'full_name': node.get('full_name'),
        'kind': node.get('kind'),
        'start_line': node.get('start_line'),
        'end_line': node.get('end_line'),
        'signature': _clip(node.get('signature', ''), BUDGET['expr_budget'] + 100),
        'docstring': _clip(node.get('docstring', ''), BUDGET['doc_budget']),
    }


def _compact_edge(edge):
    """Strip large candidates/expression blobs from a graph edge while keeping citations."""
    out = {k: edge.get(k) for k in ('source', 'target', 'relation', 'status', 'path', 'line')}
    expression = edge.get('expression')
    if expression:
        out['expression'] = _clip(expression, BUDGET['expr_budget'])
    candidates = edge.get('candidates')
    if candidates:
        out['candidates'] = list(candidates)[:3]  # disambiguation hints only
    return out


def project_root(path):
    if not path:
        raise ValueError('请配置 repository_path，指定被分析的代码项目。')
    root = Path(path).resolve(strict=True)
    if not root.is_dir():
        raise ValueError('repository_path 必须指向项目文件夹。')
    with os.scandir(root):
        pass
    return root


def source_paths(root):
    paths = []
    for folder, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED and not d.endswith('.egg-info')
                         and not (Path(folder) / d).is_symlink())
        for name in sorted(names):
            path = Path(folder) / name
            if path.is_symlink() or name.startswith('.env') or name.lower() in {'credentials.json', 'secrets.json'}:
                continue
            if path.suffix.lower() in TEXT_SUFFIXES or name in {'Dockerfile', 'Makefile'}:
                paths.append(path.relative_to(root).as_posix())
        if len(paths) > 10000:
            raise ValueError('Too many source files; select a smaller project directory')
    try:
        result = subprocess.run(['git', 'check-ignore', '--stdin', '-z'], cwd=root,
                                input='\0'.join(paths)+'\0', text=True, encoding='utf-8',
                                capture_output=True, timeout=10)
        ignored = set(result.stdout.rstrip('\0').split('\0')) if result.returncode in (0, 1) else set()
        paths = [p for p in paths if p not in ignored]
    except (OSError, subprocess.TimeoutExpired):
        pass
    return sorted(paths)


def read_text(root, relative, allowed_paths=None):
    path = (root / relative).resolve(strict=True)
    if not path.is_relative_to(root) or relative not in (allowed_paths if allowed_paths is not None else source_paths(root)):
        raise ValueError('Path is outside the readable project sources')
    raw = path.read_bytes()
    if len(raw) > 1_000_000:
        raise ValueError('File exceeds 1 MB read limit')
    if b'\0' in raw:
        raise ValueError('Binary file is not readable source')
    return raw.decode('utf-8-sig', errors='replace'), hashlib.sha256(raw).hexdigest()


def fingerprint(root):
    hashes, size = {}, 0
    for relative in source_paths(root):
        path = (root / relative).resolve(strict=True)
        if not path.is_relative_to(root):
            raise ValueError('Source path escapes project')
        raw = path.read_bytes()
        size += len(raw)
        if len(raw) > 1_000_000 or size > 30_000_000:
            raise ValueError('Source version scan exceeds size budget')
        hashes[relative] = hashlib.sha256(raw).hexdigest()
    value = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    return value, hashes


def code_tools(settings, context=None):
    root = project_root(settings.repository_path)
    context = context or {}
    expected = context.get('file_hashes', {})

    def checked_read(path, allowed_paths=None):
        content, digest = read_text(root, path, allowed_paths)
        if expected and expected.get(path) != digest:
            raise ValueError('Source changed during research; restart with current sources')
        return content, digest

    @tool
    def list_repository_files(prefix: str = '', offset: int = 0, limit: int = BUDGET['list_default_limit']):
        """List readable repository paths, optionally under a prefix; pagination is zero-based."""
        if offset < 0 or not 1 <= limit <= 200:
            raise ValueError('Invalid pagination')
        paths = [p for p in source_paths(root) if p.startswith(prefix)]
        return {'paths': paths[offset:offset+limit], 'total': len(paths),
                'next_offset': offset+limit if offset+limit < len(paths) else None}

    @tool
    def search_repository(query: str, path_prefix: str = '', offset: int = 0,
                          limit: int = BUDGET['search_default_limit'],
                          line_chars: int = BUDGET['search_line_chars'],
                          per_file: int = BUDGET['search_per_file']):
        """Find a literal case-insensitive string in readable source; returns file/line evidence without an index.
        Output is compressed: each hit keeps at most `line_chars` chars and `per_file` hits per file."""
        if not query.strip() or offset < 0 or not 1 <= limit <= 30:
            raise ValueError('Invalid query or pagination')
        if not 40 <= line_chars <= 1000 or not 1 <= per_file <= 50:
            raise ValueError('Invalid compression budget')
        hits, errors = [], []
        paths = source_paths(root)
        allowed_paths = set(paths)
        for path in paths:
            if not path.startswith(path_prefix):
                continue
            try:
                content, digest = checked_read(path, allowed_paths)
            except (OSError, ValueError) as error:
                errors.append({'path': path, 'error': str(error)})
                continue
            kept = 0
            for number, line in enumerate(content.splitlines(), 1):
                if query.casefold() in line.casefold():
                    if kept >= per_file:
                        break
                    kept += 1
                    hits.append({'path': path, 'line': number,
                                 'text': _clip(line.strip(), line_chars), 'file_hash': digest[:12]})
                    if len(hits) > offset + limit:
                        return {'hits': hits[offset:offset+limit], 'next_offset': offset+limit, 'errors': errors}
        return {'hits': hits[offset:offset+limit], 'next_offset': None, 'errors': errors}

    @tool
    def read_repository_file(path: str, start_line: int = 1, end_line: int = 100):
        """Read source lines with citations and file hash; continue using next_line when truncated.
        Character budget is capped at 10000 and at most 100 lines per call to protect a small context window."""
        if start_line < 1 or end_line < start_line or end_line-start_line >= BUDGET['read_max_lines']:
            raise ValueError('Read 1..100 lines at a time')
        content, digest = checked_read(path)
        lines = content.splitlines(keepends=True)
        if start_line > max(1, len(lines)):
            raise ValueError('Start line outside file')
        selected, last = '', start_line-1
        budget = BUDGET['read_char_budget']
        for number in range(start_line, min(end_line, len(lines))+1):
            if len(selected) + len(lines[number-1]) > budget:
                break
            selected += lines[number-1]
            last = number
        if lines and last < start_line:
            raise ValueError('Source line exceeds read budget')
        return {'path': path, 'start_line': start_line, 'end_line': last, 'content': selected,
                'file_hash': digest[:12], 'revision': context.get('revision', ''),
                'evidence_id': f'{digest[:12]}:{path}:{start_line}-{last}',
                'next_line': last+1 if last < len(lines) else None}

    tools = [list_repository_files, search_repository, read_repository_file]
    # Missing/stale/corrupt indexes never prevent the baseline tools from loading.
    try:
        repository(settings)
    except Exception:
        return tools

    def checked_index():
        if context.get('revision') and fingerprint(root)[0] != context['revision']:
            raise ValueError('Source changed during research; restart before graph queries')
        return repository(settings)

    @tool
    def resolve_symbol(name: str):
        """Find indexed Python symbols; multiple matches require disambiguation by path or ID.
        Returns compact symbol cards (docstring/signature truncated)."""
        matches = checked_index().resolve_symbol(name)[:BUDGET['resolve_max_matches']]
        return [_compact_node(node) for node in matches]

    @tool
    def read_code_symbol(symbol_id: str, start_line: int | None = None,
                         max_chars: int = BUDGET['read_code_default_chars']):
        """Read an indexed Python symbol with source citation; use next_line to continue."""
        return checked_index().read_symbol(symbol_id, max_chars=max_chars, start_line=start_line)

    @tool
    def query_code_graph(symbol_id: str, relation: str = 'callees', depth: int = 1):
        """Query static callers/callees/dependencies/implementations; implementations means declared inheritance.
        Returns at most 50 compact edges with citations."""
        result = checked_index().graph(symbol_id, relation, depth)
        result['edges'] = [_compact_edge(edge) for edge in result['edges'][:BUDGET['graph_max_edges']]]
        result['truncated'] = result.get('truncated', False) or len(result['edges']) >= BUDGET['graph_max_edges']
        if result.get('limitation'):
            result['limitation'] = _clip(result['limitation'], BUDGET['expr_budget'] * 2)
        return result

    return tools + [resolve_symbol, read_code_symbol, query_code_graph]
