from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph as CompiledGraph
from psycopg import connect
from psycopg.rows import dict_row

from config.settings import DATABASE_URL
from graph.edges import (
    should_continue_after_extract,
    should_continue_after_research,
)
from graph.nodes import (
    draft_node,
    extract_node,
    intake_node,
    research_node,
    send_node,
    store_node,
)
from schemas.models import AgentState


def build_graph() -> CompiledGraph:
    """Build the job search workflow graph."""
    connection = connect(
        DATABASE_URL,
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
    )
    checkpointer = PostgresSaver(connection)
    checkpointer.setup()

    graph = StateGraph(AgentState)
    graph.add_node("intake", intake_node)
    graph.add_node("research", research_node)
    graph.add_node("extract", extract_node)
    graph.add_node("store", store_node)
    graph.add_node("draft", draft_node)
    graph.add_node("send", send_node)
    graph.add_edge(START, "intake")
    graph.add_edge("intake", "research")
    graph.add_conditional_edges(
        "research",
        should_continue_after_research,
        {"extract": "extract", "end": END},
    )
    graph.add_conditional_edges(
        "extract",
        should_continue_after_extract,
        {"store": "store", "end": END},
    )
    graph.add_edge("store", "draft")
    graph.add_edge("draft", "send")
    graph.add_edge("send", END)

    return graph.compile(checkpointer=checkpointer, interrupt_before=["send"])
