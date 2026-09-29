"""Graph state definitions and data structures for the Deep Research agent."""

import operator
from typing import Annotated, Optional, Literal

from langchain_core.messages import MessageLikeRepresentation
from langgraph.graph import MessagesState
from pydantic import BaseModel, Field
from typing_extensions import TypedDict


###################
# Structured Outputs
###################
class ConductResearch(BaseModel):
    """Call this tool to conduct research on a specific topic."""
    research_topic: str = Field(
        description="The topic to research. Should be a single topic, and should be described in high detail (at least a paragraph).",
    )
    history_ids: list[str] = Field(default_factory=list, description="IDs of relevant retrieved reports to attach to this task; omit to pass available leads.")
    verification_targets: list[str] = Field(default_factory=list, description="Historical claims or open questions to verify against current sources.")


class HistoryAssessment(BaseModel):
    history_id: str
    claim: str
    status: Literal['verified', 'corrected', 'unverified']
    explanation: str
    evidence_ids: list[str] = Field(default_factory=list)


class ResearchResult(BaseModel):
    summary: str
    history_assessments: list[HistoryAssessment] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    status: Literal['completed', 'partial', 'failed'] = 'partial'


class ResearchComplete(BaseModel):
    """Call this tool to indicate that the research is complete."""

class Summary(BaseModel):
    """Research summary with key findings."""
    
    summary: str
    key_excerpts: str

class ClarifyWithUser(BaseModel):
    """Model for user clarification requests."""
    
    need_clarification: bool = Field(
        description="Whether the user needs to be asked a clarifying question.",
    )
    question: str = Field(
        description="A question to ask the user to clarify the report scope",
    )
    verification: str = Field(
        description="Verify message that we will start research after the user has provided the necessary information.",
    )

class ResearchQuestion(BaseModel):
    """Research question and brief for guiding research."""
    
    research_brief: str = Field(
        description="A research question that will be used to guide the research.",
    )


###################
# State Definitions
###################

def override_reducer(current_value, new_value):
    """Reducer function that allows overriding values in state."""
    if isinstance(new_value, dict) and new_value.get("type") == "override":
        return new_value.get("value", new_value)
    else:
        return operator.add(current_value, new_value)
    
class AgentInputState(MessagesState):
    """InputState is only 'messages'."""

class AgentState(MessagesState):
    """Main agent state containing messages and research data."""
    
    supervisor_messages: Annotated[list[MessageLikeRepresentation], override_reducer]
    research_brief: Optional[str]
    raw_notes: Annotated[list[str], override_reducer] = []
    notes: Annotated[list[str], override_reducer] = []
    final_report: str
    last_completed_report: str
    repository_revision: str
    repository_context: dict
    research_results: Annotated[list[dict], override_reducer]
    research_status: str
    research_iterations: int
    report_succeeded: bool
    history_question: str
    history_context: str
    history_matches: list[dict]
    history_status: str
    history_save_status: str
    history_saved_id: str

class SupervisorState(TypedDict):
    """State for the supervisor that manages research tasks."""
    
    supervisor_messages: Annotated[list[MessageLikeRepresentation], override_reducer]
    research_brief: str
    notes: Annotated[list[str], override_reducer] = []
    research_iterations: int = 0
    repository_context: dict
    history_context: str
    history_matches: list[dict]
    research_results: Annotated[list[dict], override_reducer]
    research_status: str
    raw_notes: Annotated[list[str], override_reducer] = []

class ResearcherState(TypedDict):
    """State for individual researchers conducting research."""
    
    researcher_messages: Annotated[list[MessageLikeRepresentation], operator.add]
    tool_call_iterations: int = 0
    research_topic: str
    repository_context: dict
    history_context: str
    history_matches: list[dict]
    verification_targets: list[str]
    source_evidence: Annotated[list[dict], operator.add]
    termination_reason: str
    research_result: dict
    compressed_research: str
    raw_notes: Annotated[list[str], override_reducer] = []

class ResearcherOutputState(BaseModel):
    """Output state from individual researchers."""
    
    research_result: dict = Field(default_factory=dict)
    compressed_research: str
    raw_notes: Annotated[list[str], override_reducer] = []
