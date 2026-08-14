"""LangGraph pipeline assembly. See SPEC.md's graph diagram.

Pipeline assembly only -- no business logic, no prompts, no model calls
(`.claude/add-graph-node.md`). The one exception is `await_category`: it
has no independent business logic of its own (no prompt, no model call,
no output schema) and exists purely to pause the graph for user
confirmation via LangGraph's `interrupt()` -- that's graph control flow,
not a node in the same sense as the six scaffolded under
`app/graph/nodes/` (kickoff's node-scaffolding step didn't list it
among them), so it's defined here rather than getting its own file.

Checkpointer: in-memory for now. PostgresSaver (same schema TBD) is a
later step, once Supabase is wired up -- swapping it is a one-line
change to `_checkpointer` below, not a graph restructure.

Node return values: every node in app/graph/nodes/ returns a full
GraphState via `state.model_copy(update=...)`, per CLAUDE.md's node
contract. LangGraph, given a Pydantic state schema, treats every field
*present* in a node's return value as a write to that field's channel --
including fields whose value didn't change. That's harmless when only
one node runs per step, but identify and ocr run in the same superstep
(parallel, SPEC.md's diagram), and both "write" every unchanged field
(image, user_id, ...) with identical values; the default LastValue
channel still rejects a second write in the same step even when the
values match (InvalidUpdateError). See CLAUDE.md's "Things the AI gets
wrong here" for the full failure mode. `_as_partial_update` below diffs
each node's returned state against its input and forwards only the
fields that actually changed, so parallel nodes touching disjoint
fields never collide on the ones they didn't touch. This lives here
(not in the node files) because it's exactly the kind of LangGraph
wiring detail add-graph-node.md reserves for pipeline.py -- node files
keep their documented `(state) -> GraphState` contract unchanged.

Consuming the result: a side effect of partial-update writes is that a
channel no node has written yet is *absent* from `ainvoke()`'s and
`aget_state()`'s dicts entirely, for any GraphState field with a plain
`= None` default -- `confirmed_category` before resume, or
`structured_fields` for an "other" item (extract_structured never
runs), are missing keys, not `None` values. Fields with a
`default_factory` (`confidence_scores`, `validation_errors`) are
seeded from the factory up front instead, so they're always present.
Callers that need a fully populated instance (the API layer, a later
step) should reconstruct one via `GraphState.model_validate(result)`,
which fills in every absent field's default regardless of which kind it
is, rather than KeyError-ing on the `= None` ones. See
tests/test_graph.py's test_graph_none_default_fields_stay_absent_until_written.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Literal

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt

from app.graph.nodes.category_router import category_router
from app.graph.nodes.extract_structured import extract_structured
from app.graph.nodes.generate_description_and_title import (
    generate_description_and_title,
)
from app.graph.nodes.identify import identify
from app.graph.nodes.ocr import ocr
from app.graph.nodes.validate import validate
from app.graph.state import GraphState


async def await_category(state: GraphState) -> dict[str, Any]:
    """Pause the graph for user confirmation of the suggested category.

    SPEC.md: "the user's confirmation is authoritative" -- there's no
    confidence threshold that skips this, every run pauses here. Resumed
    via `Command(resume=category)` from the API layer (`app/routers/`,
    a later step); the value `interrupt()` returns is exactly what the
    caller passed to `Command(resume=...)`.

    Returns a partial update (just the one field this node changes), not
    a full GraphState -- see this module's docstring on node return
    values. This node isn't wrapped by `_as_partial_update` (it has no
    separate `(state) -> GraphState` contract to preserve, unlike the six
    nodes under app/graph/nodes/), so it returns the partial form itself.
    """
    category = interrupt(
        {
            "suggested_category": state.suggested_category,
            "confidence": state.router_confidence,
        }
    )
    return {"confirmed_category": category}


def _route_after_description(state: GraphState) -> Literal["extract_structured", "validate"]:
    """Skip extract_structured for "other" -- no category-specific fields."""
    if state.confirmed_category == "other":
        return "validate"
    return "extract_structured"


def _as_partial_update(
    node: Callable[[GraphState], Awaitable[GraphState]],
) -> Callable[[GraphState], Awaitable[dict[str, Any]]]:
    """Adapt a node's `(state) -> GraphState` contract to LangGraph's
    per-channel write model. See this module's docstring for why.
    """

    async def _wrapped(state: GraphState) -> dict[str, Any]:
        updated = await node(state)
        return {
            name: new_value
            for name in type(state).model_fields
            if (new_value := getattr(updated, name)) != getattr(state, name)
        }

    return _wrapped


def _add_node(
    graph: StateGraph[GraphState],
    name: str,
    node: Callable[[GraphState], Awaitable[dict[str, Any]]],
) -> None:
    """Register a partial-update node.

    One type: ignore here rather than one per add_node call below.
    LangGraph's add_node overloads are typed for a node returning the
    full state model or None; a node returning a partial-update dict
    (this module's docstring explains why every node here does) doesn't
    match any of them, even though it's correct at runtime -- verified
    directly against the installed langgraph version (see this PR's
    description) and exercised end-to-end by tests/test_graph.py.
    """
    graph.add_node(name, node)  # type: ignore[call-overload]


def build_graph() -> StateGraph[GraphState]:
    """Assemble the graph. Uncompiled -- callers choose the checkpointer."""
    graph: StateGraph[GraphState] = StateGraph(GraphState)

    _add_node(graph, "category_router", _as_partial_update(category_router))
    _add_node(graph, "await_category", await_category)
    _add_node(graph, "identify", _as_partial_update(identify))
    _add_node(graph, "ocr", _as_partial_update(ocr))
    _add_node(
        graph,
        "generate_description_and_title",
        _as_partial_update(generate_description_and_title),
    )
    _add_node(graph, "extract_structured", _as_partial_update(extract_structured))
    _add_node(graph, "validate", _as_partial_update(validate))

    graph.add_edge(START, "category_router")
    graph.add_edge("category_router", "await_category")

    # identify + ocr run in parallel after resume -- both edges from the
    # same predecessor; LangGraph fans out, then joins once both reach
    # generate_description_and_title (SPEC.md's diagram).
    graph.add_edge("await_category", "identify")
    graph.add_edge("await_category", "ocr")
    graph.add_edge("identify", "generate_description_and_title")
    graph.add_edge("ocr", "generate_description_and_title")

    graph.add_conditional_edges("generate_description_and_title", _route_after_description)
    graph.add_edge("extract_structured", "validate")
    graph.add_edge("validate", END)

    return graph


_checkpointer = InMemorySaver()
compiled_graph: CompiledStateGraph[GraphState] = build_graph().compile(checkpointer=_checkpointer)
