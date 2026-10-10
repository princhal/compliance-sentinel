"""The audit graph.

load_obligations -> index_and_scan -> [check_category x N in parallel] -> aggregate
    -> notify (only when there are alert-worthy violations) -> approval (pauses for a human)
    -> generate_report

check_category is a compiled subgraph: plan_checks -> retrieve_code -> assess -> verify.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from sentinel.agent import nodes
from sentinel.agent.context import AgentContext
from sentinel.agent.state import AuditState, GroupInput, GroupOutput, GroupState


def build_category_subgraph():
    g = StateGraph(GroupState, context_schema=AgentContext, input_schema=GroupInput,
                   output_schema=GroupOutput)
    g.add_node("plan_checks", nodes.plan_checks)
    g.add_node("retrieve_code", nodes.retrieve_code)
    g.add_node("assess", nodes.assess)
    g.add_node("verify", nodes.verify)
    g.add_edge(START, "plan_checks")
    g.add_edge("plan_checks", "retrieve_code")
    g.add_edge("retrieve_code", "assess")
    g.add_edge("assess", "verify")
    g.add_edge("verify", END)
    return g.compile()


def build_graph(checkpointer=None):
    g = StateGraph(AuditState, context_schema=AgentContext)
    g.add_node("load_obligations", nodes.load_obligations)
    g.add_node("index_and_scan", nodes.index_and_scan)
    g.add_node("check_category", build_category_subgraph())
    g.add_node("aggregate", nodes.aggregate)
    g.add_node("notify", nodes.notify)
    g.add_node("approval", nodes.approval)
    g.add_node("generate_report", nodes.generate_report)
    g.add_edge(START, "load_obligations")
    g.add_edge("load_obligations", "index_and_scan")
    g.add_conditional_edges("index_and_scan", nodes.fan_out, ["check_category", "aggregate"])
    g.add_edge("check_category", "aggregate")
    g.add_conditional_edges("aggregate", nodes.route_after_aggregate, ["notify", "approval"])
    g.add_edge("notify", "approval")
    g.add_conditional_edges("approval", nodes.route_after_approval, ["generate_report", END])
    g.add_edge("generate_report", END)
    return g.compile(checkpointer=checkpointer)
