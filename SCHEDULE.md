## Three-day sequencing

### Prep (1–2 hrs): setup
- This spec (done)
- CLAUDE.md committed to repo
- Repo initialized: FastAPI backend + Expo app as sibling directories in a monorepo
- `.claude/` skill files scaffolded
- GitHub Actions CI: `ruff`, `mypy`, `pytest` for backend; `tsc`, `vitest` for mobile

### Day 1: backend + graph
- **Morning:** FastAPI scaffold, Supabase project created (Postgres + Storage + Auth), Alembic migration for `items` table, LangGraph structure with mocked Claude responses returning fixture data, end-to-end request with fake data working
- **Afternoon:** Swap mocks for real Claude calls node-by-node. Each node gets its own test with a fixture image. Parallel `identify` + `ocr`. SSE streaming working via curl.
- **Evening:** Real-item smoke test — run 2–3 actual items from the garage through the deployed backend via curl. Capture what works, what doesn't, note in CLAUDE.md.

### Day 2: mobile app
- **Morning:** Expo scaffold, Supabase Auth integration, sign-in screen working on a real device via Expo Go or dev build.
- **Afternoon:** Capture screen → upload to Supabase Storage → call backend → render streaming progress → prefilled form. Happy path only, minimal styling.
- **Evening:** Inventory list screen, edit/save, low-confidence field highlighting.

### Day 3: evals + desktop + polish
- **Morning:** Populate ground truth for 15–20 real items in `backend/evals/fixtures/` (JSON ground truth file per image). Run the baseline eval suite across all nodes with the MVP model config. Commit the report to `backend/evals/reports/`. This is the infrastructure-and-baseline run; actual experimentation (swapping models, comparing providers) is backlogged in `EXPERIMENTS.md` and not done this weekend.
- **Afternoon:** Desktop batch-upload frontend (Next.js, same backend, `POST /items/batch` endpoint with concurrent graph execution capped at 3).
- **Evening:** README with graph visualization (export from LangGraph), "what the AI gets wrong" section populated from eval results, "production migration path" paragraph, link to `EXPERIMENTS.md`, deploy preview build, generate QR code for demo.

### Cut list (in reverse priority — drop from bottom if behind)
1. Core capture → graph → prefilled form → save (never cut)
2. Inventory list (never cut)
3. Auth (cut to hardcoded user only if truly stuck; document as gap)
4. Streaming UI (fall back to multi-step spinner)
5. Low-confidence field highlighting
6. Parallel identify/ocr (run sequentially if debugging eats time)
7. Desktop batch frontend
8. Eval suite beyond 5 items

---

