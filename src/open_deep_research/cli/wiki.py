"""Build a project Wiki and knowledge graph from Python AST and optional LLM explanations."""

import argparse
import asyncio
import json
from collections import Counter

from dotenv import load_dotenv

from open_deep_research.configuration import Configuration
from open_deep_research.wiki.render import export_wiki
from open_deep_research.wiki.service import build_wiki


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root')
    parser.add_argument('--database', help='Shared SQLite database')
    parser.add_argument('--output', default='.repository-wiki', help='Export parent directory')
    parser.add_argument('--model', help='Wiki LLM; otherwise use configured research model')
    parser.add_argument('--business-dir', help='Repository-relative business Markdown directory (default: docs/business)')
    parser.add_argument('--no-llm', action='store_true', help='Extract static structure without model calls')
    args = parser.parse_args()
    load_dotenv()
    config = {'configurable': {'repository_path': args.root, 'research_database': args.database,
                               'wiki_model': args.model, 'wiki_business_dir': args.business_dir}}
    settings = Configuration.from_runnable_config(config)
    wiki = asyncio.run(build_wiki(settings, use_llm=not args.no_llm, config=config))
    destination = export_wiki(wiki, settings.repository_path, args.output)
    print(json.dumps({'output': str(destination), 'revision': wiki['revision'],
                      'pages': dict(Counter(page['status'] for page in wiki['pages'].values())),
                      'business_topics': len(wiki['graph']['business_topics']),
                      'business_analysis': dict(Counter(t['analysis_status'] for t in wiki['graph']['business_topics'].values()))},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
