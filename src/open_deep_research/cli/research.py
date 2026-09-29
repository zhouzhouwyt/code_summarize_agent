"""Run a code research question from the command line."""
import asyncio
import json
from pathlib import Path
from langchain_core.messages import HumanMessage
from open_deep_research.workflow.context import public_context


def main():
    import argparse
    from dotenv import load_dotenv
    from open_deep_research.workflow.graph import deep_researcher
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('question')
    parser.add_argument('--repository', required=True)
    parser.add_argument('--database', help='Shared SQLite database for AST and history')
    parser.add_argument('--no-history', action='store_true')
    parser.add_argument('--allow-web', action='store_true')
    args = parser.parse_args()
    config = {'configurable': {'repository_path': str(Path(args.repository).resolve()),
              'research_database': args.database, 'repository_allow_web': args.allow_web,
              'history_enabled': not args.no_history}}
    result = asyncio.run(deep_researcher.ainvoke({'messages': [HumanMessage(content=args.question)]}, config))
    print(result.get('final_report') or result['messages'][-1].content)
    print(json.dumps({'context': public_context(result.get('repository_context', {})),
                      'history': result.get('history_status'), 'save': result.get('history_save_status')},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
