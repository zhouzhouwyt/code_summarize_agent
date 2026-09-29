import asyncio
import json
import sqlite3
from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage

from open_deep_research.history import service as history
from open_deep_research.configuration import Configuration


class Embedder:
    identity = "test-question-model"
    dimension = 2

    def windows(self, text):
        for start in range(0, len(text), 100):
            yield start, min(start + 100, len(text))

    def encode(self, texts):
        return [[1, 0] if "database" in text else [0, 1] for text in texts]


def test_records_are_complete_idempotent_and_scoped(tmp_path):
    store = history.ResearchHistory(tmp_path / "history.sqlite3", Embedder())
    report = "report\n" * 1000
    first = store.save("alice", "database question", "brief", report)
    assert store.save("alice", "database question", "brief", report) == first
    store.save("bob", "database question", "brief", "private bob report")
    store.save("alice", "unrelated topic", "brief", "unrelated report")
    hits = store.search("alice", "database question", min_score=0.8)
    assert len(hits) == 1 and hits[0].report == report
    with sqlite3.connect(store.database) as connection:
        assert connection.execute("SELECT count(*) FROM research_history").fetchone()[0] == 3
    assert store.search("charlie", "database") == []
    store.embedder.identity = "other-model"
    assert store.search("alice", "database") == []


def test_long_question_stays_one_record(tmp_path):
    store = history.ResearchHistory(tmp_path / "h.sqlite3", Embedder())
    question = "database " * 100
    store.save("local", question, "brief", "full report")
    hits = store.search("local", question)
    assert len(hits) == 1 and hits[0].question == question


def test_context_is_bounded_and_marked_as_excerpt():
    hit = history.HistoryHit("id", "question", "brief", '\\"\n' * 5000, "2026-09-27", 1)
    text = history.history_context([hit], 500)
    assert len(text) <= 500
    assert json.loads(text)[0]["report_truncated"] is True
    assert history.history_context([hit], 1) == ""


def test_current_question_excludes_previous_completed_turn():
    state = {"final_report": "old report", "messages": [
        HumanMessage(content="old question"), AIMessage(content="old report"),
        HumanMessage(content="new question"), AIMessage(content="clarification?"),
        HumanMessage(content="clarification answer")]}
    assert history.current_question(state) == "new question\n\nclarification answer"


def test_disabled_failed_and_unavailable_paths(tmp_path, monkeypatch):
    config = {"configurable": {"history_database": str(tmp_path / "h.sqlite3")}}
    def fail(*args):
        raise RuntimeError("offline")
    monkeypatch.setattr(history, "_operation", fail)
    assert asyncio.run(history.retrieve_research_history({"history_question": "q"}, config))["history_status"] == "retrieval_error"
    assert asyncio.run(history.save_research_history({"report_succeeded": False}, config))["history_save_status"] == "skipped_failed_report"
    assert asyncio.run(history.save_research_history({"report_succeeded": True, "final_report": "r"}, config))["history_save_status"] == "save_error"
    config["configurable"]["history_enabled"] = False
    assert asyncio.run(history.retrieve_research_history({}, config))["history_status"] == "disabled"
    assert not (tmp_path / "h.sqlite3").exists()


def test_auth_owner_overrides_local_namespace():
    settings = Configuration()
    assert history._scope({"metadata": {"owner": "alice"}}, settings) != history._scope({"metadata": {"owner": "bob"}}, settings)
    assert history._scope({"metadata": {"owner": "bob"}, "configurable": {"langgraph_auth_user": {"identity": "alice"}}}, settings) == history._scope({"metadata": {"owner": "alice"}}, settings)

