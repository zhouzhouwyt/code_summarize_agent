"""Compatibility entry point; implementation lives in repository.index."""
from open_deep_research.cli.index import main
from open_deep_research.repository.index import RepositoryKnowledge, repository

if __name__ == '__main__':
    main()