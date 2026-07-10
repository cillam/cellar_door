# EXPERIMENTS.md

**Experiments require explicit human authorization.** This file is a backlog of considered optimizations, not a worklist. The agent does not run experiments without being asked. The "How to run an experiment" workflow below applies once a human has decided to run one.

Per-node experiment backlog for the extraction pipeline. MVP ships with Claude everywhere (see `SPEC.md` → Model tiering). This document is the plan for what gets swapped, measured, and optimized **after** the MVP is shipped — and the infrastructure that makes those experiments cheap rather than expensive.


## How to run an experiment

Every experiment uses the `ModelProvider` abstraction (`backend/app/providers/`) and the eval harness (`backend/evals/`). Workflow:

1. Implement the alternative provider if it doesn't exist (e.g., `providers/paddle_ocr.py`, `providers/ollama.py`). Must conform to the `ModelProvider` interface.
2. Register it in `providers/registry.py` under a named profile (e.g., `ocr_paddle`).
3. Run the relevant node's eval runner against the existing fixture set with the new profile:
   ```
   python -m evals.runners.ocr --provider ocr_paddle --output evals/reports/
   ```
4. Run `evals/compare.py` to diff against the baseline report.
5. Commit the report + a markdown summary in `evals/reports/`. Keep the original fixtures and ground truth untouched.

An experiment is complete when the report is committed. A "win" that isn't measured is not a win.

## Success bar for replacing Claude on a node

Any alternative must clear **all** of:

- **Accuracy parity or better** on the existing fixture set (per-field accuracy for structured nodes, human A/B judgment for description node).
- **Latency p95 ≤ current** or a documented reason the latency increase is acceptable (e.g., cost savings dominate).
- **Failure modes are evaluated as trades, not absolutes.** A change is acceptable if the new failure modes are less frequent, less severe, or more recoverable than the ones it replaces. Document new failure modes in CLAUDE.md's "Things the AI gets wrong here" section in the same PR as the model swap, with the trade-off named explicitly. Unilateral "this is just better" claims aren't sufficient — show what got worse alongside what got better.
- **Operational cost** (compute, maintenance, cold starts) accounted for, not just per-call API cost. A local model that saves $0.01/call but needs a GPU instance at $50/month is a loss at portfolio-scale volume and a win at production-scale volume — the crossover point must be stated.

---

## Node: `category_router`

**Current:** Claude Haiku via vision call. ~$0.002/call, ~1.5s p95.
**Task:** Multi-class image classification (wine / halloween / other).

### Experiment R1 — Gemini Flash
- **Hypothesis:** Gemini Flash is comparable in accuracy to Haiku at lower cost.
- **Setup:** Implement `providers/gemini.py`, register as `router_gemini`. ~30 min.
- **Win condition:** ≥95% classification accuracy on fixture set, cost ≤50% of Haiku.
- **Risk:** None material. Worst case we revert the config line.

### Experiment R2 — Fine-tuned CLIP classifier
- **Hypothesis:** A fine-tuned image classifier eliminates the API call entirely for this node.
- **Setup:** Collect 100+ labeled images per class (wine, halloween, negative examples). Fine-tune a CLIP head. Deploy via a simple inference endpoint (Modal or Replicate are fine; Fly.io with a CPU-only image since CLIP inference is cheap). ~1–2 days including data collection.
- **Win condition:** ≥95% accuracy, <50ms p95 latency, <$0.0001/call effective cost including idle compute.
- **Risk:** Data collection is the real cost. Until the pipeline has real users generating labeled data, this is premature.
- **When:** Defer until the pipeline has processed >1,000 real items.

### Experiment R3 — Haiku with text-only prompt
- **Hypothesis:** Some items are routable from OCR output alone, without a vision call. Run OCR first, check for keyword triggers ("varietal", "750ml", "Funko"), fall back to vision only if ambiguous.
- **Setup:** Refactor graph to run OCR before router; add a keyword-based fast path. ~2 hours.
- **Win condition:** >40% of items routed without a vision call; overall router cost cut >30%.
- **Risk:** Graph complexity increases. Worth it only if the cost win is material.

---

## Node: `identify`

**Current:** Claude Sonnet vision. ~$0.008/call, ~3s p95.
**Task:** Specific product identification ("Beringer Founders' Estate Cabernet 2019").

### Experiment I1 — Sonnet → Opus fallback
- **Hypothesis:** Sonnet handles the common case well; Opus is only needed for obscure/rare items. A confidence-based fallback saves cost without sacrificing quality on hard cases.
- **Setup:** Add a confidence threshold to the identify node; if Sonnet confidence < threshold, re-run with Opus. Modify graph to emit both results to the eval runner for analysis. ~2 hours.
- **Win condition:** Fallback triggers on <15% of items; overall accuracy on hard cases (low-confidence subset) improves by >10 percentage points; average cost per call stays within 10% of Sonnet-only.
- **Risk:** Adds latency on fallback cases. Acceptable if the alternative is wrong output.

### Experiment I2 — GPT-4V side-by-side
- **Hypothesis:** GPT-4V may outperform Sonnet on specific product identification for certain brands.
- **Setup:** Implement `providers/openai.py`, run the eval. ~1 hour.
- **Win condition:** Per-category accuracy uplift >5 percentage points on either wine or Halloween.
- **Value if won:** Informs a "best model per category" routing strategy.
- **Value if lost:** Data point in favor of Claude, worth documenting in the README.

### Experiment I3 — Open VLM (Qwen-VL-Max, LLaVA-Next) via HF Inference API
- **Hypothesis:** Open vision-language models have closed the gap enough to be viable.
- **Setup:** HF Inference API, implement provider, run eval. ~2 hours.
- **Win condition:** ≥90% of Sonnet's accuracy at ≥50% cost reduction.
- **Reality check:** As of early 2026 this is likely a loss on specific product ID, but the gap is closing fast enough that it's worth re-running quarterly.

---

## Node: `ocr`

**Current:** Claude Sonnet vision. ~$0.008/call, ~2.5s p95.
**Task:** Extract text from label verbatim.

### Experiment O1 — PaddleOCR
- **Hypothesis:** Dedicated OCR models are competitive with Claude on text extraction, especially at much lower cost.
- **Setup:** Implement `providers/paddle_ocr.py` (runs on CPU, no GPU required). Runs in-process or as a sidecar container. ~3 hours including containerization.
- **Win condition:** Word-level accuracy ≥ Claude on fixture set. Cost drops to ~$0.0001/call (compute only).
- **Risk:** Stylized wine label fonts may degrade Paddle's accuracy more than Claude's. The fixture set should have at least 5 stylized-font wine labels to measure this fairly.
- **Priority:** High. This is the most likely cost-saving swap.

### Experiment O2 — TrOCR (HuggingFace)
- **Hypothesis:** TrOCR's transformer architecture may handle stylized text better than Paddle's older models.
- **Setup:** HF Inference API or self-hosted. ~2 hours.
- **Win condition:** Beats both Paddle and Claude on the stylized-label subset.

### Experiment O3 — Hybrid: PaddleOCR first, Claude fallback on low confidence
- **Hypothesis:** Claude's value on OCR is only on hard cases. Route easy cases to PaddleOCR.
- **Setup:** Requires O1 to be implemented first. Add confidence threshold and fallback logic in the OCR node. ~2 hours.
- **Win condition:** >70% of calls handled by Paddle; overall accuracy matches Claude-only baseline.
- **Value:** This is the pattern that generalizes — "cheap model first, expensive model on fallback" is a pattern worth having one worked example of in the portfolio.

---

## Node: `generate_description_and_title`

**Current:** Claude Haiku text call. ~$0.001/call, ~1.5s p95.
**Task:** Two-sentence product description from identification + OCR.

### Experiment D1 — Llama 3.1 8B via Ollama (local dev) / HF Inference (deploy)
- **Hypothesis:** Text-in-text-out with a clear prompt is a solved problem for small local models. At production volume, self-hosting wins.
- **Setup:** Implement `providers/ollama.py` for local dev, `providers/hf_inference.py` for deploy. ~3 hours.
- **Win condition:** Human A/B on 30 samples: Llama's descriptions judged equivalent-or-better ≥45% of the time (not 50%, because small quality degradation is acceptable for large cost wins at scale).
- **Cost crossover:** Haiku at $0.001/call vs. an inference endpoint at ~$30/month idle. Crossover at ~30,000 photos/month.

### Experiment D2 — Skip the description entirely
- **Hypothesis:** The description is the lowest-value output. Identification + structured fields + OCR text is enough for the user to fill in prose themselves if they want.
- **Setup:** Config flag to disable the description node. Run user preference survey on demo users. ~1 hour.
- **Win condition:** Users rate the without-description experience ≥ the with-description experience.
- **Value if won:** Entire node can be deleted. Best kind of optimization.

---

## Node: `extract_structured`

**Current:** Claude Sonnet with Pydantic structured output. ~$0.010/call, ~3s p95.
**Task:** Category-specific field extraction, with null for uncertain fields.

### Experiment E1 — Haiku with structured output
- **Hypothesis:** Haiku can maintain the "return null when uncertain" behavior with sufficient prompting.
- **Setup:** Config change + prompt tuning. ~2 hours including prompt iteration.
- **Win condition:** Null-correctness rate ≥95% (i.e., Haiku returns null on items where the field genuinely isn't visible at least 95% of the time). Field accuracy on populated fields within 5 points of Sonnet.
- **Risk:** Haiku historically hallucinates more confidently on structured output. This is the experiment most likely to fail — and that failure is itself a valuable portfolio data point.
- **Priority:** High. Sonnet on this node is the largest single line item in per-photo cost.

### Experiment E2 — Gemini Flash with structured output
- **Hypothesis:** Gemini Flash supports structured output and may match Sonnet at lower cost.
- **Setup:** Extend `providers/gemini.py`. ~1 hour.
- **Win condition:** Same as E1.

### Experiment E3 — Two-pass extraction with validation retry
- **Hypothesis:** On validation failure (Pydantic rejects the output), a second pass with the validation error in the prompt recovers cleanly. This is orthogonal to the model choice — it's a pipeline change.
- **Setup:** Already in the MVP graph as the `validate` node. This experiment measures whether enabling the retry loop (currently off) improves final accuracy.
- **Win condition:** ≥80% of validation failures recover on retry without introducing new failure modes.
- **Risk:** Retry loops can mask bugs. Cap at one retry.

---

## Cross-node experiments

### Experiment X1 — Prompt caching
- **Hypothesis:** Anthropic's prompt caching feature cuts input token cost by ~90% on cached portions. The category-specific extraction prompts are long and identical across calls.
- **Setup:** Enable prompt caching on the Claude provider for the extraction node's system prompt. ~30 min.
- **Win condition:** Per-call cost on extraction node drops by >30%.
- **Priority:** Highest. Nearly free to enable, meaningful cost win, clear portfolio talking point.
- **MVP status:** Not enabled by default to keep the MVP provider minimal. First experiment to run post-MVP.

### Experiment X2 — Photo deduplication via perceptual hash
- **Hypothesis:** Users photograph the same item multiple times. A pHash cache of recently-processed photos eliminates duplicate pipeline runs.
- **Setup:** Compute pHash on upload, check against a user-scoped cache, return cached result if hit. ~2 hours.
- **Win condition:** >10% cache hit rate in real usage.
- **Scope note:** Only meaningful once there's real usage to measure against.

### Experiment X3 — Parallel graph node execution
- **Already in MVP:** `identify` and `ocr` run in parallel after the router.
- **Candidate extension:** `generate_description_and_title` can start as soon as `identify` completes, in parallel with `extract_structured`. The description doesn't strictly require OCR output — it can be regenerated if needed.
- **Setup:** Graph restructure. ~1 hour.
- **Win condition:** End-to-end p95 latency drops by >2 seconds.

---

## Things worth NOT experimenting with

Worth being explicit about dead-ends so they don't get revisited.

- **Fine-tuning Claude.** Anthropic's fine-tuning story is not mature enough (as of early 2026) to justify the setup cost for a portfolio project. Revisit in 6 months.
- **Building a custom vision transformer from scratch.** Not a portfolio-scale project.
- **Self-hosting a frontier-scale model.** 70B+ parameter models need meaningful GPU infrastructure. Not a weekend or a month project.
- **Prompt engineering alone, without evals.** "I made the prompt better" without a measurement is not an experiment, it's a guess.

---

## Running log of completed experiments

(Populated after the MVP ships. Each entry links to the report in `evals/reports/`.)

| Date | Experiment | Status | Outcome | Report |
|------|-----------|--------|---------|--------|
| _TBD_ | X1 — Prompt caching on extraction | _planned_ | — | — |
| _TBD_ | O1 — PaddleOCR vs. Claude on OCR | _planned_ | — | — |
| _TBD_ | E1 — Haiku on structured extraction | _planned_ | — | — |

Three experiments is a realistic first-month target. Running all of them is not.
