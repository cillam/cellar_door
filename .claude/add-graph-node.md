# Skill: Add a graph node

You execute this skill when the human asks you to add a new node to the LangGraph extraction pipeline — for example, a pre-processing node (image quality check), an enrichment node (category-specific metadata lookup), or a new branch of the router.

New nodes are architectural additions to the pipeline. Do not propose or add them unprompted.

Before you start, answer in the PR description:

1. What state does this node consume, and what does it add? Nodes are pure functions over `GraphState`. If your node needs information the state doesn't carry, add a field to `GraphState`; don't route data around some other way.
2. Where does this node go in the graph? Reference the diagram in `SPEC.md`. If it creates a new branch or parallel path, call that out.

The human should have identified the node's known failure mode (every model-calling node has one). If they haven't, ask before proceeding — a node without a documented failure mode is a node whose failure mode you haven't found yet.

If you're adding a node that calls a model, read the `ModelProvider` abstraction in `backend/app/providers/` first. Nodes never import `anthropic` directly.

## File layout

One node per file. File name matches node name. Location: `backend/app/graph/nodes/<node_name>.py`.

Each node file exports exactly one async function:

```python
async def node_name(state: GraphState) -> GraphState:
    ...
```

Prompts live in `backend/app/graph/prompts/<node_name>.py` as triple-quoted string constants. Do not inline prompts in the node file. Do not use external `.txt` files.

## Steps

### 1. Define the state extension

In `backend/app/graph/state.py`, add any new fields the node will write. Use `None` defaults so partial state is always valid:

```python
class GraphState(BaseModel):
    # existing fields...
    new_node_output: SomeType | None = None
```

### 2. Write the prompt (if model-calling)

In `backend/app/graph/prompts/<node_name>.py`:

```python
NODE_NAME_PROMPT = """Your task is to ...

Return null for any field you cannot determine. Do not guess.

Known failure modes:
- ...
"""
```

The "return null if uncertain" clause is required for any node with structured output. The "known failure modes" section starts with the failure mode the human provided and grows as verification finds new ones.

### 3. Write the node

Template:

```python
from app.graph.state import GraphState
from app.graph.prompts.node_name import NODE_NAME_PROMPT
from app.providers import registry

async def node_name(state: GraphState) -> GraphState:
    provider = registry.provider_for("node_name")  # resolves via registry
    result = await provider.complete_structured(
        prompt=NODE_NAME_PROMPT,
        image=state.image,         # if vision
        schema=SomeOutputSchema,
    )
    return state.model_copy(update={"new_node_output": result})
```

Import the `registry` module itself, not `provider_for` directly. Tests
mock this call by monkeypatching `registry.provider_for` — that only
reaches call sites that look it up through the module each time. A
`from app.providers.registry import provider_for` binds a local name at
import time that a later `monkeypatch.setattr` on the registry module
won't reach.

Rules:

- Typed input, typed output. No `dict[str, Any]` return values.
- Never mutate `state` in place. Always return a new state via `model_copy(update=...)`.
- Never import `anthropic` or any SDK directly. Go through `provider_for(node_name)`.
- Handle `None` inputs gracefully. If an upstream node returned null for something this node depends on, decide explicitly: skip (return state unchanged), return an explicit null for this node's output, or raise. Never silently pass through.

### 4. Wire into the graph

In `backend/app/graph/pipeline.py`:

```python
graph.add_node("node_name", node_name)
graph.add_edge("upstream_node", "node_name")
graph.add_edge("node_name", "downstream_node")
```

For conditional edges (branching), use `graph.add_conditional_edges()` with a typed routing function.

For parallel execution (two nodes running after the same predecessor), just add both edges from the predecessor. LangGraph handles concurrency.

### 5. Register the node's model tier

In `backend/app/providers/registry.py`:

```python
NODE_MODEL_CONFIG = {
    # existing...
    "node_name": {"provider": "claude", "tier": "haiku"},  # or "sonnet"
}
```

Choose the cheapest tier that meets the accuracy bar. Default to Haiku unless you have a reason.

### 6. Write the node's unit test

In `backend/tests/test_nodes/test_<node_name>.py`:

```python
async def test_node_name_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    provider_mock = make_mock_provider(node_name="node_name", returns=...)
    monkeypatch.setattr(registry, "provider_for", lambda node_name: provider_mock)

    state = GraphState(image=load_fixture("wine_beringer_2019.jpg"), user_id=uuid4())
    result = await node_name(state)

    assert result.new_node_output.field == expected_value
    assert provider_mock.called_with_prompt_containing("...")
```

The node signature never takes a provider parameter — it always resolves
one internally via `registry.provider_for(node_name)` (see step 3 above).
Tests mock the provider by monkeypatching `app.providers.registry`'s
`provider_for`, which every node's internal call goes through, rather
than injecting a provider directly. This mocks the provider (so CI
doesn't spend Claude budget) and lets the test assert both the output
shape and that the prompt was called with the right content.

### 7. Add at least one end-to-end fixture

Add a fixture image and update `backend/tests/test_graph.py` to run the full pipeline through the new node. The graph-level test uses a mocked provider; real Claude runs happen only in `backend/evals/`.

### 8. Add an eval runner (if model-calling)

In `backend/evals/runners/<node_name>.py`, write a runner that:

- Loads the ground-truth fixture set
- Runs the node against a given provider (via CLI flag)
- Produces a scored report (per-fixture accuracy + aggregate cost/latency)

See `.claude/add-eval-case.md` for the fixture + ground-truth format.

### 9. Flag the SPEC.md graph diagram for update

The diagram in `SPEC.md` must reflect the current graph. SPEC.md is human-edited, so include an updated ASCII diagram in the PR description or a comment. The human commits the SPEC.md change; do not edit SPEC.md yourself.

## Verification before merging

- [ ] Node is in its own file under `backend/app/graph/nodes/`
- [ ] Prompt is in its own file under `backend/app/graph/prompts/`
- [ ] Unit test passes with a mocked provider
- [ ] End-to-end graph test passes
- [ ] Node is registered in `providers/registry.py` with an explicit model tier choice
- [ ] Updated SPEC.md graph diagram is included in the PR for human review
- [ ] Eval runner exists (if model-calling)
- [ ] CI green: `ruff`, `mypy --strict`, `pytest`

## What NOT to do

- Do not put logic in `pipeline.py`. Pipeline assembly only — no business logic, no prompts, no model calls.
- Do not call the provider directly from `pipeline.py`. Providers are resolved inside nodes via the registry.
- Do not write a node that reads from the DB or makes HTTP calls to external services. If the node needs external data, stop and ask — that's a different kind of node and needs a service layer, which is an architectural decision.
- Do not edit SPEC.md. Propose the diagram update in the PR; the human commits it.
- Do not skip the eval runner. A model-calling node without an eval runner is an untestable liability.