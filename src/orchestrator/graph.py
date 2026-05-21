from __future__ import annotations

from langgraph.graph import StateGraph, END

from src.orchestrator.state import GraphState
from src.agents.research import run as research_agent
from src.agents.sanctions import run as sanctions_agent
from src.agents.ubo import run as ubo_agent
from src.agents.risk_assessment import run as risk_agent
from src.models import KYCReport


async def compile_report(state: GraphState) -> dict:
    """Orchestrator node: assemble the final KYCReport from agent outputs."""
    report = KYCReport(
        entity=state["entity"],
        research_findings=state["research_findings"],
        sanctions_results=state["sanctions_results"],
        ubo_structure=state["ubo_structure"],
        risk_rating=state["risk_rating"],
        flags=state.get("flags", []),
    )
    return {"report": report}


def build_graph() -> StateGraph:
    graph = StateGraph(GraphState)

    # Register nodes
    graph.add_node("research", research_agent)
    graph.add_node("sanctions", sanctions_agent)
    graph.add_node("ubo", ubo_agent)
    graph.add_node("risk_assessment", risk_agent)
    graph.add_node("compile_report", compile_report)

    # Research, Sanctions, and UBO run in parallel after the start
    graph.set_entry_point("research")
    graph.add_edge("research", "sanctions")
    graph.add_edge("research", "ubo")

    # Risk assessment waits for all three upstream agents
    graph.add_edge("sanctions", "risk_assessment")
    graph.add_edge("ubo", "risk_assessment")

    # Final compilation
    graph.add_edge("risk_assessment", "compile_report")
    graph.add_edge("compile_report", END)

    return graph


# Compiled graph — import this in the API layer
kyc_graph = build_graph().compile()
