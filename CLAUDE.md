# CLAUDE.md

This file is the context contract for you (the AI agent or agents) working on this repo. Read it before touching code.

## When SPEC.md and CLAUDE.md disagree

SPEC.md wins for product behavior (what the app does, what the API returns, what the pipeline produces). CLAUDE.md wins for engineering conventions (how code is organized, what tools are used, what coding rules apply). If they appear to conflict on something else, the safe default is to flag the conflict in the PR and ask rather than guess.

## Who edits which file

- **SPEC.md is human-edited only.** The agent may surface conflicts, propose changes in PR descriptions, or quote relevant sections — but never modifies SPEC.md without explicit human instruction. Product behavior is a human decision.
- **CLAUDE.md is agent-editable within bounds.** The agent updates the "Things the AI gets wrong here" section when it discovers new failure modes. The agent updates the "Known gotchas" section when an anticipated gotcha turns out to need clarification. Other sections (tech stack, conventions, directory structure) require human approval before edits.
- **Eval fixtures and ground truth (`backend/evals/fixtures/*.json`) are human-edited only.** Ground truth is the authoritative reference the agent's output is measured against; the agent rewriting it would defeat the measurement. If a fixture's ground truth appears wrong, the agent flags it in a PR comment and continues against the existing ground truth.
- **EXPERIMENTS.md and ROADMAP.md are human-edited only.** These represent product and engineering planning decisions.
- **Skills (`.claude/*.md`) are agent-editable.** When the agent discovers a better way to do a recurring task, it should update the skill in the same PR as the change that taught it the lesson.

If you are about to edit a file in violation of this list, stop and ask a human first.

## What this project is

A mobile-first home inventory app for wine and Halloween collectibles, plus a catch-all Other category. User takes a photo, a LangGraph pipeline identifies the item, OCRs the label, generates a description, and extracts structured fields into a prefilled form.

- See `SPEC.md` for the full product spec including the graph diagram, API contract, and acceptance criteria.
- See `EXPERIMENTS.md` for the backlog of per-node model experiments (local models, alternative OCR, cost optimization). MVP uses Claude everywhere; the `ModelProvider` abstraction exists specifically to make those experiments cheap later. **You do not run experiments without explicit human instruction.**
- See `ROADMAP.md` for deferred features (location tracking, barcode entry, price/rating lookup, multi-user sharing, additional categories). Before proposing a new feature, check if it's already on the roadmap as a deliberate deferral.

## Tech stack (locked — do not swap without an updated SPEC.md)

- **Mobile:** Expo (React Native) + TypeScript, expo-router, expo-camera, supabase-js
- **Backend:** Python 3.12, FastAPI, LangGraph, LangChain (`langchain-anthropic`), Pydantic v2, asyncpg, httpx
- **DB:** Supabase Postgres, Alembic for migrations
- **Storage:** Supabase Storage (signed upload URLs)
- **Auth:** Supabase Auth, JWT verified on backend
- **AI:** Claude via Anthropic API, structured outputs via Pydantic discriminated unions
- **Deploy:** FastAPI → Railway, mobile → Expo preview builds
- **CI:** GitHub Actions — backend (`ruff`, `mypy --strict`, `pytest`), mobile (`tsc --noEmit`, `vitest`, `eslint`)

## Directory conventions

```
/
├── CLAUDE.md                 ← this file
├── SPEC.md                   ← product spec
├── .claude/                  ← custom skills for recurring tasks
│                                (add-item-category, add-graph-node,
│                                 add-migration, add-eval-case, etc.)
├── backend/
│   ├── app/
│   │   ├── main.py           ← FastAPI entrypoint
│   │   ├── auth.py           ← JWT verification dependency
│   │   ├── db.py             ← DB connection + session
│   │   ├── models/           ← Pydantic schemas (BaseItem, WineItem, HalloweenItem, OtherItem)
│   │   ├── routers/          ← API routes (items, health)
│   │   ├── providers/        ← ModelProvider abstraction
│   │   │   ├── base.py       ← ModelProvider interface
│   │   │   ├── claude.py     ← default: Anthropic implementation
│   │   │   └── registry.py   ← resolves node → provider → model
│   │   ├── graph/            ← LangGraph pipeline
│   │   │   ├── pipeline.py   ← graph assembly
│   │   │   ├── nodes/        ← one file per node
│   │   │   └── prompts/      ← prompt templates as strings
│   │   └── storage.py        ← Supabase Storage client
│   ├── alembic/              ← migrations
│   ├── evals/                ← eval harness (first-class, not afterthought)
│   │   ├── fixtures/         ← real photos + ground-truth JSON sidecars
│   │   ├── runners/          ← one runner per node
│   │   ├── compare.py        ← CLI: diff two providers on one node
│   │   └── reports/          ← committed markdown reports, dated
│   ├── tests/
│   │   ├── fixtures/         ← small fixture images for unit tests (distinct from evals/)
│   │   ├── test_nodes/       ← per-node unit tests with fixtures
│   │   ├── test_graph.py     ← end-to-end graph tests
│   │   ├── test_providers.py ← ModelProvider contract tests
│   │   └── test_routes.py    ← API route tests
│   └── pyproject.toml
├── mobile/
│   ├── app/                  ← expo-router routes
│   ├── components/
│   ├── lib/
│   │   ├── supabase.ts       ← Supabase client
│   │   └── api.ts            ← typed API client for backend
│   ├── tests/
│   └── package.json
└── .github/workflows/
    └── ci.yml
```

## Coding conventions

### Python (backend)

- **Pydantic v2 everywhere.** No dicts floating around as "data." Every inter-module boundary is a Pydantic model. The WineItem/HalloweenItem/OtherItem discriminated union is the single source of truth for item schemas — DB serialization, Claude structured output, and API responses all use the same classes.
- **Type everything.** `mypy --strict` is a hard CI gate. No `Any`, no untyped `dict`, no `# type: ignore` without a comment explaining why.
- **Async all the way down.** FastAPI routes are `async def`. DB calls via `asyncpg`. LangGraph nodes are async. No `requests`, use `httpx`.
- **No bare `except:`.** Catch specific exceptions. Anthropic errors, Pydantic validation errors, and asyncpg errors each have their own handling.
- **Prompts live in `graph/prompts/` as triple-quoted strings in `.py` files**, not as separate `.txt` files. Easier to version, easier to test, easier to parameterize.
- **One graph node per file.** File name matches node name. Each node exports a single async function with a typed signature taking `(state: GraphState) -> GraphState`.
- **Every model call goes through the `ModelProvider` interface** (see `providers/base.py`). Nodes never import `anthropic` directly. This is non-negotiable — it's what makes per-node model experimentation possible without refactoring. The provider emits structured usage events (model, input tokens, output tokens, latency, estimated cost) which the eval harness consumes.
- **Model selection per node is configuration, not code.** `providers/registry.py` maps node name → provider → model tier. Changing the extraction node from Sonnet to Haiku is a one-line config change, testable against evals.
- **Ruff for linting and formatting.** Default config is fine. Run on save.

### TypeScript (mobile)

- **Strict mode on.** `tsc --noEmit` is a CI gate.
- **No `any`.** Use `unknown` and narrow.
- **The API client (`lib/api.ts`) is the only place that talks to the backend.** Components never `fetch` directly.
- **API types are shared via a generated client** — run `openapi-typescript` against the FastAPI OpenAPI schema. The types on the mobile side are the types on the backend side. If they drift, CI fails.
- **React components are function components with hooks.** No classes.
- **No inline styles.** Use `StyleSheet.create` or NativeWind/Tailwind if added.

### Shared

- **Never commit secrets.** `.env.example` in both `backend/` and `mobile/` lists required env vars with placeholder values. Real `.env` files are gitignored. CI uses GitHub secrets.
- **Commits are small and green.** Every commit passes CI. No "WIP broken, will fix next commit" — use a branch or a stash.
- **PRs describe the "why," not the "what."** The diff shows the what.

## Testing conventions

### The quality gate

A change is ready to merge when:
1. `ruff check`, `mypy --strict`, and `pytest` pass on the backend
2. `tsc --noEmit`, `vitest run`, and `eslint` pass on the mobile app
3. The change has a test that would have failed before the change

Run the gates locally before pushing. CI is a backstop, not a first-try discovery tool — if you're pushing to see if CI passes, you've already lost 5 minutes and slowed down every collaborator (human or agent) waiting on the build.

### What gets tested

- **Every graph node has a unit test with a fixture image** in `backend/tests/fixtures/`. The test asserts the node's output shape and at least one specific field value. Fixtures are small (resize to 800px) and committed to the repo.
- **The full graph has an end-to-end test** that runs all nodes with a fixture image and asserts the final payload.
- **Every API route has a route test** that exercises happy path + auth failure + validation failure.
- **Mobile components have component tests** for components with conditional rendering or user-triggered state changes (low-confidence field highlighting, form validation, category switcher). Purely presentational components don't need tests.

### What doesn't get tested

- Claude API calls in CI. Node tests mock the `ModelProvider` and assert it was called with the right prompt and schema. Real Claude runs only in the evals suite (see below), which is run manually and not on CI.
- Supabase in CI. Use testcontainers for Postgres; mock Supabase Storage and Auth at the client boundary.

### Evals (distinct from tests)

Evals live in `backend/evals/` and are a first-class artifact of this repo. They're not CI tests — they cost real money and take minutes to run. They exist to measure model quality per node and to enable the experiments backlogged in `EXPERIMENTS.md`.

- **Every node has an eval runner** in `evals/runners/` that takes a `ModelProvider` and the fixture set and produces a scored report (accuracy per field, cost per call, latency p50/p95).
- **Fixtures are real items** — actual wine bottles and Halloween collectibles photographed by a human, with human-written ground-truth JSON sidecars.
- **Eval reports are committed** to `evals/reports/` with a date and the provider config. Historical reports are the audit trail for "does this change make the pipeline better or worse?"
- **Never delete fixtures or ground truth.** If ground truth is wrong, the human fixes the JSON and notes the correction in the git log. You never edit ground truth — if a fixture's ground truth appears to be wrong, you flag it in a PR comment for human review and continue against the existing ground truth. The fixture set only grows.
- **New failure modes add new fixtures.** If verification finds a case the pipeline fails on, that case becomes a fixture before the fix is merged. See `.claude/add-eval-case.md`.

**Eval enforcement is on the honor system for this project.** Evals are not CI-gated. The PR template includes a checkbox prompting the author to confirm they ran evals for touched nodes and committed the report. Claude's automated PR review (see below) will also flag prompt or provider changes that lack an accompanying eval report.

### Automated PR review

This repo uses the official Claude Code GitHub Action to review every PR automatically. The workflow lives at `.github/workflows/claude.yml` and is configured with a project-specific review prompt that flags:

1. Violations of the `ModelProvider` abstraction (direct Anthropic SDK imports in graph nodes)
2. Missing fixtures or eval reports for touched nodes
3. Hallucination vectors in prompts that don't enforce the node contracts from SPEC.md
4. Authorization checks missing on endpoints that reference user resources
5. Immutable-field violations on PATCH endpoints

Claude's review is advisory, not blocking. Unaddressed review comments that match the rules above should be fixed or explicitly responded to in the PR.

## Agent workflow

### Starting a new feature

1. Read SPEC.md for the feature's acceptance criteria.
2. Read this file.
3. Read the relevant skill in `.claude/` if one exists.
4. Write the failing test first. If you can't write the test, you don't understand the feature yet — go back to the spec or ask a human.
5. Implement the feature.
6. Run the quality gate locally.
7. Update this file's "things the AI gets wrong here" section if you hit a new failure mode.

### Context management

- **Load only what the task needs.** For a typical task, that's CLAUDE.md plus the handful of files actually being changed and their immediate dependencies. Don't load the whole backend "to be safe" — extra files crowd out reasoning room and increase cost per call.
- **Reset the session when context degrades.** Signs: many files loaded, or a conversation that's spanned several turns and drifted. Cramming more context into a struggling session usually makes it worse; a fresh session with a tighter scope usually unblocks it.

### Sub-agent decomposition

The four backend/mobile workstreams can run as parallel agent sessions:
1. DB schema + Supabase setup + auth dependency
2. LangGraph pipeline (nodes + graph assembly)
3. API routes + SSE streaming
4. Mobile app (capture → form → save)

Streams 2 and 3 depend on the Pydantic models from stream 1. Stream 4 depends on the API contract from stream 3 (via the generated OpenAPI client). Publish the Pydantic models and the OpenAPI schema early, and any schema changes after that require coordination with any streams consuming them. Coordinate via these typed interfaces, not via shared code changes.

## Things the AI gets wrong here

Observed failure modes found during development or verification. This section is deliberately empty until real failures are discovered — anticipated failure modes live in "Known gotchas" below. Entries here are evidence-based: something the pipeline actually did wrong, with a fix and a regression test.

### Parallel nodes conflict when they return a full GraphState

**Symptom:** `langgraph.errors.InvalidUpdateError: At key 'image': Can receive only one value per step` when `identify` and `ocr` (which run in parallel per SPEC.md's diagram) are both wired into the compiled graph and invoked together — surfaced immediately on the first end-to-end pipeline test, not in any single node's isolated unit test.

**Why it happens:** Every node's documented contract (this file, `.claude/add-graph-node.md`) has it return a full `GraphState` via `state.model_copy(update={...})`. LangGraph, given a Pydantic state schema, treats every field *present* in a node's return value as a write to that field's channel — including fields whose value didn't change. That's invisible when only one node runs per step (each node file's own unit test only ever exercises it alone), but the moment two nodes run in the same superstep and both "write" an unchanged shared field (e.g. `image`) with identical values, the default `LastValue` channel still rejects the second write in that step, even though the values agree.

**Fix:** Node files and their contract (`(state: GraphState) -> GraphState`, returning a full copy) are unchanged — the fix lives entirely in `app/graph/pipeline.py`, which is pipeline-assembly's job. `_as_partial_update` wraps each node, diffs its returned state against its input, and forwards only the fields that actually changed. A related consequence worth knowing: a `GraphState` field with a plain `= None` default stays *absent* (not `None`-valued) from `ainvoke()`/`aget_state()` output until some node actually writes it; fields with a `default_factory` (`confidence_scores`, `validation_errors`) are seeded from the factory up front and are always present. `GraphState.model_validate(result)` is the safe way to hydrate a fully-defaulted instance from either kind. See `pipeline.py`'s module docstring for the full explanation.

**Regression test:** `backend/tests/test_graph.py` — the wine/halloween/other happy-path tests exercise the parallel identify+ocr branch directly (this bug fails the *first* one immediately); `test_graph_none_default_fields_stay_absent_until_written` pins down the absent-vs-seeded-default distinction.

### Template for new entries

```
### [Short name of the failure mode]

**Symptom:** What the AI produced.
**Why it happens:** The root cause.
**Fix:** Prompt change, schema change, validation rule, or explicit guidance in this file.
**Regression test:** Path to the test that catches this.
```

### Known gotchas (anticipated, before implementation)

These are failure modes we expect based on prior experience with vision models and similar pipelines. Each has a mitigation planned; if the mitigation works, that's good. If it doesn't, the failure graduates to the section above with an entry describing what actually happened.

- **Wine vintages on stylized labels.** Big ornate numerals on premium wine labels confuse vision models into reading them as year + something else. Expected mitigation: the OCR cross-reference rule in `extract_structured`'s contract, plus an adversarial fixture with a known-stylized vintage.
- **OCR invention on label-free items.** Vision models will confidently fabricate plausible label text when no text is present on the item. Expected mitigation: the three-state OCR contract (`text_present` / `text_unreadable` / `no_text`) makes "no text" a first-class output. Adversarial fixtures with `must_not_contain` lists catch regressions.
- **Category confusion on ambiguous items.** A wine-themed Halloween decoration exists. Expected mitigation: the router returns a suggestion, the user always confirms, the user's choice is authoritative.
- **Forgetting to verify user_id on graph resume.** The resume endpoint must check that the paused graph's `user_id` (stored in graph state) matches the JWT's `user_id` before calling `Command(resume=...)`. Missing this check is an authorization bypass — any authenticated user could resume any paused graph by guessing thread_ids. Covered by the "Resume auth and lifecycle" acceptance criterion.

## Performance targets

These are estimates based on typical Claude API latencies, not measurements. They'll be validated and adjusted during a real-item verification pass. They're engineering targets for machine-side latency and exclude human reaction time (e.g., the user looking at the category picker).

- **Router phase (photo upload → category picker visible):** under 3s p95
- **Extraction phase (category confirmed → form visible):** under 12s p95
- **Total pipeline (sum of router + extraction phases):** under 15s p95
- **Image upload** (resized JPEG to Supabase Storage over cellular): under 5s p95 — if slower, revisit image resize strategy

## What's explicitly out of scope in this repo

Don't add these without a spec update. The ROADMAP.md file captures deferred features — check it before assuming something is a new feature request vs. a deliberate deferral.

Specifically out of MVP scope:
- Price lookups against external APIs (see ROADMAP.md)
- Quality rating lookups against external APIs (see ROADMAP.md)
- Barcode scanning (see ROADMAP.md)
- Multi-user sharing (see ROADMAP.md)
- Additional categories beyond wine, Halloween, and Other (see ROADMAP.md)
- Item location tracking — rooms, boxes, QR codes (see ROADMAP.md)
- Any kind of "social" feature
- Web scraping of producer/manufacturer sites

If you find yourself writing code for any of the above, stop and ask a human before continuing.
