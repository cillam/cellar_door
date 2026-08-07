# Inventory

A mobile-first home inventory app for wine and collectibles. Take a photo of an item, and an AI pipeline identifies it, reads the label, generates a description, and extracts structured fields into an editable form. Save it, and it's in your inventory.

Built as a three-day project to demonstrate AI-native engineering practice — spec-first workflow, agent harness engineering, per-node model tiering, and a real eval suite over real items.

## Status

🚧 **In active development.** This README is a stub. It will be filled in with:

- Architecture overview with graph visualization
- Demo video / QR code for the Expo preview build
- Eval results (accuracy per node, cost per photo, latency)
- "What the AI gets wrong" — failure modes documented from real-item verification
- Links to `SPEC.md`, `CLAUDE.md`, and `EXPERIMENTS.md`

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

_Filled in once the stack is shipped._

```bash
# Backend
cd backend
# ...

# Mobile
cd mobile
# ...
```

## Project layout

```
/
├── CLAUDE.md            ← context contract
├── SPEC.md              ← product spec
├── EXPERIMENTS.md       ← per-node experiment backlog
├── README.md            ← you are here
├── .claude/             ← custom skills
├── backend/             ← FastAPI + LangGraph
└── mobile/              ← Expo app
```


