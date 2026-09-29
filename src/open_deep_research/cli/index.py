"""Build repository AST snapshots in the shared SQLite database."""
import json
from open_deep_research.repository.index import repository


def main():
    import argparse
    from open_deep_research.configuration import Configuration
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root')
    parser.add_argument('--database', help='Shared SQLite database for AST and history')
    args = parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv()
    settings = Configuration.from_runnable_config({'configurable': {
        'repository_path': args.root, 'research_database': args.database}})
    store = repository(settings, build=True)
    print(json.dumps({k: store.data[k] for k in ('revision', 'diagnostics')}, indent=2))


if __name__ == '__main__':
    main()
