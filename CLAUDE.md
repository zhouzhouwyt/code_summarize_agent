# Repository development notes

This repository contains one supported LangGraph: `src/open_deep_research/workflow/graph.py:deep_researcher`.
Read `README.md` and `docs/code_research_workflow.md` for the current design.

Keep the original clarification, brief, supervisor and researcher loops. All requests use the supervisor.
Indexes, versions and history are optional enhancements, not entry gates. Do not reintroduce source
chunk/module embedding retrieval or the retired three-way direct-answer workflow.

Run `python -m pytest tests -q -p no:cacheprovider`; optional real local embedding check:
`python -m tests.manual.check_local_history`. LLM integration tests mock model responses.

Keep deployment auth, local environment and credentials intact. Research history is application data,
separate from Engramory memory. Do not restore legacy graphs, sample reports or old research benchmarks.
