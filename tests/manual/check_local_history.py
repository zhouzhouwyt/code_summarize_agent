"""Offline smoke check of real history embeddings and optional AST persistence."""
import tempfile
from pathlib import Path
from open_deep_research.history.embeddings import LocalEmbedder
from open_deep_research.repository.index import RepositoryKnowledge
from open_deep_research.history.service import ResearchHistory


def main():
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder) / 'repo'
        root.mkdir()
        (root / 'orders.py').write_text('def create_order():\n    return 1\n', encoding='utf-8')
        database = Path(folder) / 'research.sqlite3'
        index = RepositoryKnowledge(root, database)
        index.build()
        index.load()
        assert index.resolve_symbol('create_order')
        history = ResearchHistory(database, LocalEmbedder())
        wanted = history.save('local', 'How are orders created and stock reserved?', 'Trace order creation', 'Read orders.py')
        history.save('local', 'How do I export monthly financial reports?', 'Export reports', 'Unrelated report')
        hits = history.search('local', 'How are orders created and stock reserved?\n\nTrace order creation', min_score=0)
        assert hits[0].id == wanted and hits[0].report == 'Read orders.py'
        print('Real history embeddings, full-report retrieval and AST persistence passed.')


if __name__ == '__main__':
    main()
