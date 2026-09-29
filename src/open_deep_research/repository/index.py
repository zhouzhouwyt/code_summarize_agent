"""Optional versioned Python AST index; no source or module embeddings."""

import ast
import hashlib
import io
import json
import os
import sqlite3
from contextlib import closing
import subprocess
import tokenize
from pathlib import Path

from open_deep_research.storage.database import connect_database


EXCLUDED = {".git", ".venv", "venv", "__pycache__", "node_modules", "site-packages",
            ".research-history", ".repository-knowledge", ".repository-wiki", ".engramory-memory", ".pytest_cache", "build", "dist"}


def scan(root):
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Repository must be a directory")
    paths = []
    for folder, directories, names in os.walk(root, followlinks=False):
        directories[:] = sorted(d for d in directories if d not in EXCLUDED and not (Path(folder) / d).is_symlink())
        paths.extend((Path(folder) / n).relative_to(root).as_posix() for n in sorted(names)
                     if n.endswith(".py") and not (Path(folder) / n).is_symlink())
    if len(paths) > 10000:
        raise ValueError("Repository exceeds 10000 Python files")
    try:
        ignored = subprocess.run(["git", "check-ignore", "--stdin", "-z"], cwd=root,
                                 input="\0".join(paths) + ("\0" if paths else ""), text=True,
                                 encoding="utf-8", capture_output=True, timeout=15)
        excluded = set(ignored.stdout.rstrip("\0").split("\0")) if ignored.returncode in (0, 1) else set()
    except (OSError, subprocess.TimeoutExpired):
        excluded = set()
    files = {}
    total_bytes = 0
    for relative in paths:
        if relative in excluded:
            continue
        path = (root / relative).resolve(strict=True)
        if not path.is_relative_to(root):
            raise ValueError("Source path escapes repository")
        raw = path.read_bytes()
        if len(raw) > 1_000_000:
            raise ValueError(f"Python file exceeds 1 MB: {relative}")
        total_bytes += len(raw)
        if total_bytes > 30_000_000:
            raise ValueError("Repository source exceeds 30 MB")
        encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
        files[relative] = {"source": raw.decode(encoding), "sha256": hashlib.sha256(raw).hexdigest()}
    if not files:
        raise ValueError("No Python source files found; first version supports Python only")
    return files


def revision(files):
    return hashlib.sha256(json.dumps({p: f["sha256"] for p, f in sorted(files.items())}, sort_keys=True).encode()).hexdigest()


class References(ast.NodeVisitor):
    def __init__(self):
        self.calls, self.imports, self.assigned = [], [], set()
    def visit_Call(self, node):
        self.calls.append((ast.unparse(node.func), node.lineno))
        self.generic_visit(node)
    def visit_Import(self, node):
        self.imports.append(node)
    visit_ImportFrom = visit_Import
    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Store):
            self.assigned.add(node.id)
    def visit_FunctionDef(self, node):
        pass
    visit_AsyncFunctionDef = visit_FunctionDef
    visit_ClassDef = visit_FunctionDef


class RepositoryKnowledge:
    def __init__(self, root, database):
        self.root = Path(root).resolve(strict=True)
        self.database = Path(database)
        self.data = None

    def build(self):
        files = scan(self.root)
        nodes, pending, diagnostics = {}, [], []
        module_ids = {}
        for path, entry in files.items():
            try:
                tree = ast.parse(entry["source"], filename=path)
            except SyntaxError as error:
                diagnostics.append({"path": path, "error": str(error)})
                continue
            module_name = path.removesuffix(".py").replace("/", ".").removesuffix(".__init__")
            module_ids[module_name] = path + "::@module"
            def visit(node, parent=None, local=""):
                is_module = isinstance(node, ast.Module)
                name = module_name if is_module else node.name
                qual = module_name if is_module else (local + "." + name if local else name)
                sid = path + "::" + ("@module" if is_module else qual + "@" + str(node.lineno))
                kind = "module" if is_module else "class" if isinstance(node, ast.ClassDef) else "method" if parent and nodes[parent]["kind"] == "class" else "function"
                start = 1 if is_module else min([node.lineno] + [d.lineno for d in node.decorator_list])
                end = len(entry["source"].splitlines()) if is_module else node.end_lineno
                refs = References()
                for statement in node.body:
                    refs.visit(statement)
                signature = "" if is_module else ast.get_source_segment(entry["source"], node).splitlines()[0]
                nodes[sid] = dict(id=sid, path=path, name=name, qualified_name=qual,
                                  full_name=module_name + "." + qual if not is_module else module_name,
                                  kind=kind, parent=parent, start_line=start, end_line=end,
                                  docstring=ast.get_docstring(node) or "", signature=signature)
                arguments = {a.arg for a in (node.args.posonlyargs + node.args.args + node.args.kwonlyargs)} if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else set()
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    arguments |= {a.arg for a in (node.args.vararg, node.args.kwarg) if a}
                pending.append((sid, refs, module_name, getattr(node, "bases", []), arguments))
                # Descend through control-flow nodes but give nested definitions their own scope.
                def children(container):
                    for child in ast.iter_child_nodes(container):
                        if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                            visit(child, sid, "" if is_module else qual)
                        else:
                            children(child)
                children(node)
            visit(tree)
        edges, aliases, shadowed = [], {}, {}
        for sid, refs, module_name, bases, arguments in pending:
            node = nodes[sid]
            if node["parent"]:
                edges.append(dict(source=node["parent"], target=sid, relation="CONTAINS", status="resolved", path=node["path"], line=node["start_line"]))
            aliases[sid] = {}
            shadowed[sid] = refs.assigned | arguments
            for imported in refs.imports:
                if isinstance(imported, ast.Import):
                    pairs = [(a.asname or a.name.split('.')[0], a.name if a.asname else a.name.split('.')[0]) for a in imported.names]
                else:
                    package = module_name.split('.') if node['path'].endswith('/__init__.py') else module_name.split('.')[:-1]
                    prefix = '.'.join(package[:len(package) - imported.level + 1]) if imported.level else ''
                    base = '.'.join(v for v in (prefix, imported.module or '') if v)
                    pairs = [(a.asname or a.name, base + '.' + a.name) for a in imported.names if a.name != '*']
                aliases[sid].update(pairs)
                destinations = [a.name for a in imported.names] if isinstance(imported, ast.Import) else [target for _, target in pairs]
                for destination in destinations:
                    edges.append(dict(source=sid, target=None, expression=ast.unparse(imported),
                                      imported_name=destination, relation="IMPORTS",
                                      status="syntactic", path=node["path"], line=imported.lineno))
        def resolve(expression, sid):
            head, *tail = expression.split('.')
            scope = sid
            while scope:
                if scope != sid and nodes[scope]['kind'] == 'class':
                    scope = nodes[scope]['parent']
                    continue
                if head in shadowed[scope]:
                    return []
                if head in aliases[scope]:
                    expanded = '.'.join([aliases[scope][head]] + tail)
                    return [n['id'] for n in nodes.values() if n['full_name'] == expanded or n['full_name'].endswith('.' + expanded)]
                child = [n for n in nodes.values() if n['parent'] == scope and n['name'] == head]
                if child:
                    target_name = child[0]['full_name'] + ('.' + '.'.join(tail) if tail else '')
                    return [n['id'] for n in nodes.values() if n['full_name'] == target_name]
                scope = nodes[scope]['parent']
            return []
        # Resolve import destinations to modules where possible, preserving external imports.
        for edge in edges:
            if edge['relation'] != 'IMPORTS':
                continue
            destination = edge['imported_name']
            candidates = sorted({mid for name, mid in module_ids.items()
                                 if name == destination or name.endswith('.' + destination)})
            if not candidates and '.' in destination:
                parent_module = destination.rsplit('.', 1)[0]
                candidates = sorted({mid for name, mid in module_ids.items()
                                     if name == parent_module or name.endswith('.' + parent_module)})
            edge['candidates'] = candidates
            edge['target'] = candidates[0] if len(candidates) == 1 else None
            edge['status'] = 'resolved' if len(candidates) == 1 else 'ambiguous' if candidates else 'unresolved'
        for sid, refs, module_name, bases, arguments in pending:
            for expression, line, relation in ([(c, line, 'CALLS') for c, line in refs.calls] +
                                               [(ast.unparse(base), base.lineno, 'INHERITS') for base in bases]):
                targets = resolve(expression, sid)
                # Attribute dispatch such as self.foo remains unresolved without type analysis.
                status = 'resolved' if len(targets) == 1 else 'ambiguous' if targets else 'unresolved'
                edges.append(dict(source=sid, target=targets[0] if len(targets) == 1 else None,
                                  candidates=targets, expression=expression, relation=relation,
                                  status=status, path=nodes[sid]['path'], line=line))
        data = dict(schema=2, root=str(self.root), revision=revision(files), files=files,
                    nodes=nodes, edges=edges, diagnostics=diagnostics)
        with closing(connect_database(self.database)) as db:
            db.execute('INSERT INTO repository_snapshots (root,data) VALUES (?,?) '
                       'ON CONFLICT(root) DO UPDATE SET data=excluded.data',
                       (str(self.root), json.dumps(data, ensure_ascii=False)))
            db.commit()
        self.data = data
        return dict(revision=data['revision'], files=len(files), symbols=len(nodes), relations=len(edges), diagnostics=diagnostics)

    def load(self):
        if not self.database.is_file():
            raise ValueError('Repository index missing; build it first')
        with closing(sqlite3.connect(self.database)) as db:
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='repository_snapshots'").fetchone()
            row = db.execute('SELECT data FROM repository_snapshots WHERE root=?', (str(self.root),)).fetchone() if exists else None
        if row is None:
            raise ValueError('Repository index missing; build it first')
        data = json.loads(row[0])
        if data['schema'] != 2 or Path(data['root']).resolve() != self.root:
            raise ValueError('Repository index root/schema mismatch')
        if revision(scan(self.root)) != data['revision']:
            raise ValueError('Repository changed; rebuild the knowledge index before querying')
        self.data = data
        return self

    def resolve_symbol(self, name):
        nodes = self.data['nodes']
        if name in nodes:
            return [nodes[name]]
        exact = [n for n in nodes.values() if name in {n['qualified_name'], n['full_name']}]
        return exact or [n for n in nodes.values() if n['name'] == name]

    def read_symbol(self, symbol_id, max_chars=8000, start_line=None):
        node = self.data['nodes'][symbol_id]
        lines = self.data['files'][node['path']]['source'].splitlines(keepends=True)
        start = node['start_line'] if start_line is None else start_line
        if not node['start_line'] <= start <= node['end_line'] or not 1 <= max_chars <= 30000:
            raise ValueError('Invalid source range/budget')
        content, end = '', start - 1
        for number in range(start, node['end_line'] + 1):
            if len(content) + len(lines[number - 1]) > max_chars:
                break
            content += lines[number - 1]
            end = number
        if end < start:
            raise ValueError('First source line exceeds read budget; request a larger max_chars budget')
        return dict(evidence_id=f"{self.data['revision'][:12]}:{symbol_id}:{start}-{end}",
                    revision=self.data['revision'], symbol_id=symbol_id, path=node['path'],
                    start_line=start, end_line=end, content=content,
                    truncated=end < node['end_line'], next_line=end + 1 if end < node['end_line'] else None)

    def graph(self, symbol_id, relation='callers', depth=1):
        if symbol_id not in self.data['nodes'] or not 1 <= depth <= 3:
            raise ValueError('Unknown symbol or invalid depth (1..3)')
        relation_map = {'callers': ('CALLS', True), 'callees': ('CALLS', False),
                        'implementations': ('INHERITS', True), 'dependencies': ('IMPORTS', False)}
        if relation not in relation_map:
            raise ValueError('Unsupported relation')
        kind, reverse = relation_map[relation]
        frontier, visited, found = {symbol_id}, {symbol_id}, []
        for _ in range(depth):
            next_frontier = set()
            for edge in self.data['edges']:
                if edge['relation'] != kind:
                    continue
                key = edge['target'] if reverse else edge['source']
                if key not in frontier:
                    continue
                found.append(edge)
                nxt = edge['source'] if reverse else edge['target']
                if nxt and nxt not in visited:
                    next_frontier.add(nxt)
            visited |= next_frontier
            frontier = next_frontier
        unresolved = sum(e['relation'] == kind and e['status'] in {'unresolved', 'ambiguous'} for e in self.data['edges'])
        return dict(revision=self.data['revision'], symbol_id=symbol_id, relation=relation, edges=found[:100],
                    truncated=len(found) > 100, unresolved_in_repository=unresolved,
                    limitation='Static Python bindings only; dynamic dispatch, reflection and interface protocols are not fully resolved. implementations means declared inheritance, not exhaustive runtime implementations.')


def repository(settings, build=False):
    """Only explicit build requests create indexes; runtime callers can fall back."""
    root = Path(settings.repository_path).resolve(strict=True)
    store = RepositoryKnowledge(root, settings.research_database)
    if build:
        store.build()
    else:
        store.load()
    return store
