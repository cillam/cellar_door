# Inventory

![CI](https://github.com/cillam/cellar_door/actions/workflows/ci.yml/badge.svg)

A mobile-first home inventory app for wine and collectibles. Take a photo of an item, and an AI pipeline identifies it, reads the label, generates a description, and extracts structured fields into an editable form. Save it, and it's in your inventory.

Built to demonstrate AI-native engineering practice — spec-first workflow, agent harness engineering, per-node model tiering, and a real eval suite over real items.

## Status

**Backend: built, deployed, and verified end-to-end.** Mobile app: not started.

- ✅ FastAPI + LangGraph backend, scaffolded, tested, and CI-gated (`ruff`, `mypy --strict`, `pytest`)
- ✅ `ModelProvider` abstraction (interface + Claude implementation + per-node model tiering) — see `EXPERIMENTS.md` for what it unlocks later
- ✅ Full six-node LangGraph pipeline (`category_router`, `identify`, `ocr`, `generate_description_and_title`, `extract_structured`, `validate`), including the human-in-the-loop category-confirmation pause/resume
- ✅ All seven REST endpoints (photo capture + resume, item CRUD), auth-checked and user-scoped
- ✅ Real Supabase wiring: Postgres (items table + LangGraph's `AsyncPostgresSaver` checkpointer), Storage, JWKS-verified Auth
- ✅ All five model-calling nodes running against real Claude (Haiku/Sonnet per SPEC.md's tiering), verified against real wine-bottle photos
- ✅ Deployed to Railway, verified end-to-end via the real API: `POST /items/from-photo` → SSE through category confirmation → `/resume` → SSE through a completed, structured item
- ⬜ Mobile app (Expo) — deliberately deferred; see `kickoff_prompt.txt`
- ⬜ `backend/evals/` — the formal eval harness (real fixtures, ground truth, per-node accuracy/cost/latency reports) isn't built yet. Node quality so far has been checked via ad-hoc verification against real photos, not the committed eval suite CLAUDE.md describes.
- ⬜ Architecture diagram, demo video/QR code, and a written "what the AI got wrong" retrospective

See `CLAUDE.md`'s "Things the AI gets wrong here" section for the failure modes actually hit (and fixed) during development — that log is maintained live, in the same PR as the fix, not written up separately after the fact.

## The harness, before the code

Before any feature code was written, the project shipped a context contract and a set of skills that govern how agents work on this repo:

- [`SPEC.md`](./SPEC.md) — product spec, graph diagram, API contract, acceptance criteria
- [`CLAUDE.md`](./CLAUDE.md) — The context contract: tech stack, directory conventions, coding conventions, testing gates, failure-mode log.
- [`EXPERIMENTS.md`](./EXPERIMENTS.md) — per-node experiment backlog for cost and quality optimization. MVP uses Claude everywhere; the `ModelProvider` abstraction exists specifically to make these experiments cheap to run later.
- [`.claude/`](./.claude/) — custom skills for recurring tasks: adding an item category, adding a graph node, adding a migration, adding an eval case.

These files exist as an **agent harness** — the infrastructure around the agent that makes its output reliable. The harness was committed as a single atomic commit before any feature code. The commit hash is the starting point of the actual development timeline.

## Stack (locked)

- **Mobile:** Expo (React Native) + TypeScript
- **Backend:** FastAPI + LangGraph + Pydantic v2, Python 3.12
- **DB + Storage + Auth:** Supabase (Postgres + object storage + Auth)
- **AI:** Claude via Anthropic API, structured outputs via Pydantic discriminated unions
- **Deploy:** Railway (backend) + Expo preview builds (mobile)

See `SPEC.md` for the full architecture diagram and `CLAUDE.md` for the reasoning behind each choice.

## Running locally

```bash
# Backend
cd backend
uv sync

# Secrets: point at your own env file (falls back to backend/.env if unset)
export CELLAR_DOOR_ENV_FILE=/path/to/your/.env  # see backend/.env.example for required vars

uv run uvicorn app.main:app --reload

# Quality gate (same checks CI runs)
uv run ruff check .
uv run ruff format --check .
uv run mypy --strict app tests
uv run pytest

# Mobile
# Not started yet.
```

## Project layout

```
/
├── CLAUDE.md              ← context contract
├── SPEC.md                ← product spec
├── EXPERIMENTS.md         ← per-node experiment backlog
├── ROADMAP.md             ← deliberately deferred features
├── README.md              ← you are here
├── .claude/               ← custom skills
├── backend/               ← FastAPI + LangGraph, deployed to Railway
│   ├── app/
│   │   ├── main.py        ← FastAPI entrypoint
│   │   ├── auth.py        ← JWKS-verified JWT auth
│   │   ├── db.py          ← asyncpg pool
│   │   ├── storage.py     ← Supabase Storage client
│   │   ├── models/        ← Pydantic item schemas
│   │   ├── routers/       ← API routes
│   │   ├── providers/     ← ModelProvider abstraction
│   │   └── graph/         ← LangGraph pipeline, nodes, prompts
│   ├── alembic/           ← DB migrations
│   └── tests/
└── mobile/                ← Expo app (not started)
```
