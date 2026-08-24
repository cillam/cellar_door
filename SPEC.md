# Inventory MVP — Spec

**Owner:** [you]
**Status:** Draft, locked before implementation begins

---

## Problem

I have wine in a rack and Halloween collectibles in the garage. Neither is cataloged. I want to walk up to an item, take a photo on my phone, and end up with a saved inventory entry with most fields prefilled correctly by a model and the rest editable by me.

## User story (MVP)

As a user with a phone, I open the app and sign in. I tap an add item button and take a photo of an item. A message pops up confirming the item category. I can either confirm the selected category or change it to a different category. I then wait while the backend identifies it, reads any text (if any) on the item, generates a description, and extracts category-specific structured fields. I land on a form prefilled with any data gathered from the identification and text extraction, edit anything wrong or fill in empty fields, and save. The item appears in my inventory list.


## Non-goals (MVP)

- Desktop app 
- Multi-user sharing, collaboration, or public inventories
- Any automated price lookup — API, web search, or scraping (user enters estimated value manually)
- Any automated quality rating lookup depending on item category
- Barcode scanning
- Offline mode
- Categories beyond wine, Halloween, and a generic "Other" (architecture must support adding more without a rewrite)
- Native iOS/Android builds published to App Store (Expo dev build / preview build is the demo surface)

## Categories in scope

Wine and Halloween collectibles, plus a catch-all Other for items that don't fit either. Additional specific categories (books, comics, Christmas, etc.) can be added post-MVP as new Pydantic subclasses + form components + graph branches — not schema migrations. Items saved as Other can be reclassified into new categories when those categories ship.

---

## Architecture overview

```
┌─────────────┐      ┌──────────────┐      ┌───────────────────────┐
│  Expo app   │─────▶│  Supabase    │      │  FastAPI on Railway   │
│  (iOS/And.) │      │  Storage     │      │                       │
│             │      │  (photos)    │      │  ┌─────────────────┐  │
│             │◀─────│              │      │  │  LangGraph      │  │
│             │      └──────────────┘      │  │  extraction     │  │
│             │                            │  │  pipeline       │  │
│             │─── POST /from-photo ──────▶│  └─────────────────┘  │
│             │◀────── SSE stream ─────────│           │           │
│             │   (through await_category) │           ▼           │
│             │                            │  ┌─────────────────┐  │
│             │─── POST .../resume ───────▶│  │  Claude API     │  │
│             │◀────── SSE stream ─────────│  │  (Anthropic)    │  │
│             │     (through complete)     │  └─────────────────┘  │
│             │                            │                       │
│             │      ┌──────────────┐      │                       │
│             │      │  Supabase    │◀─────│  (items schema)       │
│             │─────▶│  Postgres    │◀─────│  (langgraph schema:   │
│             │      │              │      │   PostgresSaver       │
│             │      └──────────────┘      │   checkpoints)        │
│             │                            │                       │
│             │      ┌──────────────┐      │                       │
│             │─────▶│  Supabase    │      │                       │
│             │      │  Auth (JWT)  │──────│  (verifies JWT +      │
│             │      └──────────────┘      │   thread_id ownership)│
└─────────────┘                            └───────────────────────┘
```

**Data flow for photo capture:**

1. Mobile requests a signed upload URL from Supabase Storage
2. Mobile uploads photo directly to Supabase Storage
3. Mobile calls POST /items/from-photo with the storage path in the request body and the JWT in the Authorization header.
4. FastAPI verifies JWT, loads image from Storage, runs LangGraph pipeline
5. FastAPI streams per-node updates back via SSE
6. Mobile renders prefilled form
7. User edits and saves → `POST /items` with the final payload
8. FastAPI writes to Supabase Postgres

---

## The graph

The LangGraph pipeline. Nodes are Claude calls unless noted otherwise.

```
   ┌──────────────────┐
   │  category_router │ ◀── Claude vision: wine | halloween | other
   └────────┬─────────┘         + confidence score
            │
            ▼
   ┌──────────────────┐
   │    interrupt:    │ ◀── graph pauses via interrupt();
   │  await_category  │     resumes via Command(resume=category)
   └────────┬─────────┘     with user's confirmed category
            │
            ▼
    ┌──────────────┐      ┌──────────────┐
    │   identify   │─────▶│     ocr      │   (parallel after resume)
    │   (vision)   │      │   (vision)   │
    └──────┬───────┘      └──────┬───────┘
           │                     │
           └──────────┬──────────┘
                      ▼
     ┌─────────────────────────────────┐
     │ generate_description_and_title  │ ◀── text, combines id + ocr
     └────────────────┬────────────────┘
                      │
               Check category
              /            \
             /              \
          other          wine and halloween
            │                     │
            │        ┌──────────────────────────┐
            │        │  extract_structured      │ ◀── Pydantic structured output
            │        │  (category-specific)     │     per category schema;
            │        └────────────┬─────────────┘     skipped if "other"
            │                     │
            └──────────┬──────────┘
                       ▼
          ┌──────────────────────────┐
          │        validate          │ ◀── Pydantic validation; on fail,
          │   (non-AI, Pydantic)     │     blank invalid fields + flag
          └────────────┬─────────────┘
                       ▼
                 return payload
```

**Streaming:** Use LangGraph `.stream(stream_mode="updates")` → FastAPI `StreamingResponse` with SSE. Client keys events by node name (handles parallel node completion in any order).

**Parallel nodes:** `identify` and `ocr` run concurrently after the router — independent inputs (same image, different prompts), independent outputs.

### Node contracts (beyond the happy path)

The graph above describes the happy path. Each model-calling node must handle the specific failure modes below explicitly. These are contracts, not guidelines — violations are tracked as fixture-backed bugs.

**`category_router`**
- Produces a suggested category — "wine", "halloween", or "other" — with a confidence score in [0.0, 1.0]. The suggestion pre-selects the user's category picker but is never authoritative.
- Returns "other" when neither wine nor halloween is a reasonable match.
- The graph always pauses after this node for user confirmation. The user's choice is authoritative; the router's suggestion can be accepted or overridden.
- Must not classify based on ambient context (background objects, surrounding scene).

**`identify`**
- Must include a `confidence` score in [0.0, 1.0].
- On low confidence (<0.5), return a generic description grounded in visible features ("a tall dark green wine bottle," "a small ceramic figurine of a cartoon ghost") rather than a specific-but-uncertain guess ("possibly a Beringer Cabernet," "possibly a Hallmark Casper ornament"). Specificity implies confidence; hedging with "possibly" in the output is not a substitute for setting confidence correctly.

**`ocr` — three-state contract**

This node must distinguish three distinct output states. The prompt enforces this explicitly:

1. **`text_present`** — Text is visible and readable. Return the transcribed text with high confidence. The transcription must be verbatim (not summarized, not corrected for presumed misspellings).
2. **`text_unreadable`** — Text is visible on the item but cannot be read (blurry, occluded, heavily stylized, partial). Return empty string with `reason: "unreadable"`. Do NOT guess what the text probably says based on the item type or surrounding context.
3. **`no_text`** — No text is present on the item at all (wax seal, embossed-only logo, unlabeled item). Return empty string with `reason: "no_text"`.

The critical failure mode this contract prevents: when there is no text to transcribe, vision models will confidently fabricate plausible text based on priors about what items of that type "usually say." A wax-sealed wine bottle becomes "CHÂTEAU RÉSERVE 2018"; an unlabeled ceramic pumpkin becomes "HAPPY HALLOWEEN 2023." This is always wrong, is high-confidence wrong, and contaminates the downstream description node. The three-state contract catches it by making "no text" a first-class output rather than an absence of the normal output.

**`generate_description_and_title`**
- Produces two fields: `title` (short display name, ≤5 words) and `description` (one-paragraph prose).
- If `ocr` returned `text_present`, incorporate verbatim text into the description; title may reference it but need not quote it verbatim.
- If `ocr` returned `text_unreadable` or `no_text`, generate both title and description from visual features only. Do NOT reference or fabricate label text in either field.
- `identify`'s output is valid evidence for both title and description (unlike for structured fields). Title and description are editable drafts the user verifies by eye; the user will see and correct identify's mistakes. But neither field may go beyond what identify established — no invented provenance, age, origin, or specificity that identify didn't support.
- For an "other"-category item, title and description come from visual features and any OCR text. No category-specific assumptions.

**`extract_structured`**
- For each category-specific field, the value must be supported by evidence from the item itself: visible text on the label, or deterministic inference from visible evidence (e.g., country from region where region uniquely determines country). If neither, the field is `null`. Confidence score for a null field is `0.0`, not `null`. BaseItem fields (`description`, `notes`, `estimated_value`) are not this node's responsibility.
- Numeric fields (vintage, year) must be supported by OCR output. A value passes if the digits appear in the OCR text, or if the value can be deterministically derived from text that does appear (e.g., "Nineteen Ninety-Nine" → 1999). Values not supportable by either test are nulled, regardless of the model's stated confidence.
- `identify`'s output may inform what extraction looks for, but may not alone populate a field. Every populated structured field must have label-level evidence — visible text on the item, or deterministic inference from visible text. Identify's guess that this is "probably a Beringer Cabernet" is not sufficient to populate `producer="Beringer"`; that requires "Beringer" to appear in the OCR output or be visually clearly present on the label.
- For an "other"-category item, node is skipped since there are no category-specific fields.

**Wine-specific rules for `extract_structured`:**

Region vs. appellation:
- `region` is the broad geographic area the wine comes from (Napa Valley, Burgundy, Champagne).
- `appellation` is the specific identifier for the wine within its region. Populate with either a formal legal designation (AVA, AOC, DOCG, DOP) or a widely-recognized sub-region within regions whose sub-regions aren't formal appellations (e.g., Champagne's five sub-regions: Montagne de Reims, Vallée de la Marne, Côte des Blancs, Côte de Sézanne, Côte des Bar).
- When the label shows only a region with no finer subdivision, populate `region` and leave `appellation` null.
- Named vineyards, climats, crus, and specific plots (Les Clos, Cannubi, To Kalon) do NOT go in `appellation`. Mention them in the description instead.

Varietal exception for monovarietal appellations:
- General rule: `varietal` must appear on the label. Do NOT infer varietal from producer name, region, or model priors about what wineries typically make.
- Exception: some appellations legally require a specific single grape variety. For these, populate `varietal` from the appellation even when varietal is not printed on the label. Examples include Chablis (Chardonnay), Barolo (Nebbiolo), Sancerre (Sauvignon Blanc for white, Pinot Noir for red), Brunello di Montalcino (Sangiovese), Cornas (Syrah), and Burgundy Grand/Premier Cru wines from the Côte d'Or (Chardonnay for whites, Pinot Noir for reds).
- Only apply this exception when the appellation's legal specifications require a single specific grape variety. Do NOT apply to appellations that permit blends: Bordeaux (all levels), Rioja, standard Champagne (without Blanc de Blancs/Noirs designation), Côtes du Rhône, or any American AVA (all AVAs permit multiple varietals).
- When populating varietal via this exception, add a note to the description indicating the source: e.g., "Chardonnay inferred from Chablis Grand Cru appellation."
- When uncertain whether an appellation qualifies, leave `varietal` null. Null is always the safe answer.

Bottled_in vs. region:
- `bottled_in` is the physical location of the winery that bottled the wine, from the "produced and bottled by" line on the label. It is a specific city or municipality plus state/country (e.g., "St. Helena, California", "Épernay, France").
- Never infer `bottled_in` from `region`. A wine from Napa Valley wasn't necessarily bottled in Napa Valley.

**`validate`**
- Non-model node. Runs Pydantic on the extraction output. On validation failure: blank the invalid fields, flag them in `confidence_scores` as `0.0`, add the validation error to the response payload for user visibility. Do NOT retry in the MVP (retry is planned in `EXPERIMENTS.md` as E3).

### Adversarial inputs the pipeline must handle

A regression test exists for each of these. Fixtures live in `backend/evals/fixtures/` with the `adversarial_` prefix in the filename.

| Input | Expected behavior |
|---|---|
| Wine bottle with no label (wax seal, embossed only) | Router: wine. OCR: `no_text`. Description: visual features only, no fabricated text. Extraction: all category-specific fields null. |
| Halloween item with no markings (generic ceramic pumpkin) | Router: halloween. OCR: `no_text`. Description: visual features only, no fabricated text. Extraction: all category-specific fields null. |
| Blurry photo, label visible but unreadable | Router: best-effort on shape. OCR: `unreadable`. Identify: low confidence, generic description. Description: hedges without fabricating label text. Extraction: all category-specific fields null. |
| Ambiguous category (wine-themed Halloween decoration) | Router suggests the category with highest confidence. User's confirmation may accept or override. |
| Item in neither wine nor halloween (a stapler) | Router suggests other. User confirms. Pipeline runs identify/ocr/description; extract_structured is skipped. User lands on a form with title, description, notes, estimated_value, and no category-specific fields. |
| Multiple items in frame | Pipeline runs on the whole image as if it were one item. Output may be incomplete but must not fabricate; fields that can't be determined from a composite view are null. |
| Text in a language the model handles poorly | OCR returns what it can with lowered confidence. Identify hedges. Extraction populates only fields the model is confident about. |
| Photo of a photo / screen / printout | Pipeline treats the depicted item as the subject. No detection of the indirection. |

---

### Model tiering (MVP)

Every node uses Claude via the `ModelProvider` abstraction (see CLAUDE.md). Model choice per node is configuration, not hardcoded. MVP defaults:

| Node | Model | Reasoning |
|---|---|---|
| `category_router` | Claude Haiku | 3-class classification; quality sufficient, cost ~5x lower than Sonnet |
| `identify` | Claude Sonnet | Specific product identification; quality matters most here |
| `ocr` | Claude Sonnet | Stylized labels benefit from vision-LLM context over dedicated OCR |
| `generate_description_and_title` | Claude Haiku | Text-in-text-out, no reasoning required |
| `extract_structured` | Claude Sonnet | Instruction-following ("return null if uncertain") matters |
| `validate` | n/a | Pure Pydantic, no model call |

Rough per-photo cost at these settings: **~$0.025–0.035**. Alternatives (local models, dedicated OCR, other providers) are documented in `EXPERIMENTS.md` as planned work, not implemented in MVP.

### Cost model

- **Claude API per photo:** ~$0.03 (see tiering above)
- **Development + demo period (3-day build + ~2 months of portfolio demos):** ~$10–15 total Claude spend across ~300–500 photos
- **Railway compute:** ~$5/month (hobby plan floor)
- **Supabase:** $0 on free tier for portfolio-scale usage
- **At production scale (1k photos/month):** Claude costs dominate (~$30/month) and the experiments in `EXPERIMENTS.md` become economically justified

---

## Schemas

Single `items` table. Base fields as real columns, category-specific fields in a `details` JSONB column. Pydantic discriminated union on `category` parses the right subclass.

### BaseItem

- `id: UUID`
- `user_id: UUID` (from Supabase Auth JWT)
- `category: Literal["wine", "halloween", "other"]` (discriminator)
- `photo_url: str` (Supabase Storage path)
- `title: str` (AI-generated, user-editable prose)
- `description: str` (AI-generated, user-editable prose)
- `notes: str | None` (user free-text escape valve for anything the schema doesn't capture)
- `estimated_value: Decimal | None` (user-entered; no price lookup in MVP)
- `confidence_scores: dict[str, float]` (per-field 0.0–1.0 from the extraction node; UI uses this to flag low-confidence fields)
- `created_at: datetime`
- `updated_at: datetime`

### WineItem(BaseItem)

- `producer: str | None` — winery or producer name as printed on the label
- `vintage: int | None` — year the grapes were harvested. May be null for non-vintage wines.
- `type: Literal["red", "white", "rose", "sparkling", "dessert", "fortified"] | None` — broad wine category
- `varietal: str | None` — grape variety or blend name (e.g., "Cabernet Sauvignon", "Pinot Noir", "Blend"). May be null for old-world wines where the label shows the appellation instead of the grape. See the extraction contract for the monovarietal-appellation exception.
- `style: str | None` — sweetness or house style within a type (e.g., "Brut", "Reserve Brut", "Demi-Sec", "Dry", "Late Harvest", "Ruby", "Tawny")
- `region: str | None` — broad geographic area the wine comes from (e.g., "Napa Valley", "Burgundy", "Champagne", "Bordeaux")
- `appellation: str | None` — specific identifier for the wine within its region. Either a formal legal designation (AVA, AOC, DOCG, DOP) or a widely-recognized sub-region within regions whose sub-regions aren't formal appellations (e.g., "St. Helena AVA", "Bâtard-Montrachet", "Chablis Grand Cru", "Barolo DOCG", "Côte des Bar" for Champagne). Cru distinctions, named vineyards, and specific plots (Les Clos, Cannubi) do NOT go here — those belong in the description.
- `country: str | None` — country of production
- `bottled_in: str | None` — city or municipality of the bottling facility, from the "produced and bottled by" line on the label (e.g., "Épernay, France", "St. Helena, California")
- `bottle_size: str | None` (e.g., "750ml", "1.5L")

### HalloweenItem(BaseItem)

- `manufacturer: str | None`
- `character_or_series: str | None`
- `year: int | None`
- `edition: str | None` (e.g., "limited", "standard")
- `condition: Literal["mint", "good", "fair", "poor"] | None`

### OtherItem(BaseItem)
No additional fields

All category-specific fields are nullable because the model may not find them on the label, and a blank field is a correct answer when the information isn't there. **Never allow the model to invent a value for a field it can't see** — this is enforced by the extraction prompt and verified in the validation node.

---

## API contract

### `POST /items/from-photo`

Request:
```json
{ "storage_path": "photos/<user_id>/<uuid>.jpg" }
```
The backend verifies that `storage_path` begins with `photos/<user_id>/` where `<user_id>` matches the authenticated user's ID from the JWT. Requests with a mismatched path prefix return 403.

Response: SSE stream, events keyed by node name. The stream runs the router, then closes after emitting `await_category`. The graph's paused state is persisted via LangGraph's PostgresSaver checkpointer, keyed by `thread_id`.

```
event: session
data: {"thread_id": "01HXYZ..."}

event: category_router
data: {"suggested_category": "wine", "confidence": 0.94}

event: await_category
data: {"thread_id": "01HXYZ...", "suggested_category": "wine", "confidence": 0.94, "ttl_seconds": 3600}

[stream closes; graph paused at interrupt]
```

Client renders each event as it arrives for progress UI.

### `POST /items/from-photo/{thread_id}/resume`

Request:
```json
{ "category": "wine" | "halloween" | "other" }
```

Resumes the paused graph via `Command(resume=category)`. The backend verifies `state.user_id == jwt.user_id` before resuming.

Errors:
- 403 if `thread_id`'s `user_id` doesn't match the JWT's `user_id`
- 410 if the checkpoint is older than 1 hour
- 409 if the graph has already been resumed

Response: SSE stream from resume through `complete`. The `complete` event is the only one whose payload should populate the form.

```
event: identify
data: {"best_guess": "Beringer Founders' Estate Cabernet Sauvignon 2019", "confidence": 0.88}

event: ocr
data: {"state": "text_present", "text": "BERINGER\nFOUNDERS' ESTATE\nCABERNET SAUVIGNON\n2019\nCALIFORNIA\n750ML 13.5% ALC/VOL", "reason": null}

event: generate_description_and_title
data: {"title": "...", "description": "..."}

event: extract_structured
data: {"fields": {...}, "confidence_scores": {...}}

event: complete
data: {full ItemDraft payload, unsaved, id=null}
```

### `POST /items`

Request: complete `WineItem | HalloweenItem | OtherItem` payload (edited by user).
Response: saved item with `id` populated. The `id` and `user_id` fields are server-assigned. Client-provided values for either are ignored.

### `GET /items`

Response: array of the user's items, newest first by `created_at`, for the inventory list screen.

### `GET /items/{id}`

Response: single item detail.

### `PATCH /items/{id}`

Updates an existing item. Request body is a partial payload containing only the fields the user changed. Server applies the changes and returns the full updated item.

Request example (user updated estimated_value only):
```json
{ "estimated_value": 45.00 }
```

Response: the full updated item.

The backend verifies the item's `user_id` matches the authenticated user's ID. Mismatched or nonexistent item returns 404 (same response for both). The following fields are immutable after save and cannot be changed via PATCH: `id`, `user_id`, `category`, `photo_url`, `created_at`, `confidence_scores`. Attempting to change any of these returns 400. Mutable fields are `title`, `description`, `notes`, `estimated_value`, and all category-specific fields (e.g., wine's `vintage`, halloween's `year`). The `updated_at` timestamp is refreshed server-side on every successful PATCH.

### `DELETE /items/{id}`

Deletes an item owned by the authenticated user. Returns 204 on success, 404 if the item doesn't exist or belongs to another user (same response for both to avoid leaking existence across users).

### Auth

Any endpoint that accepts a storage path or resource ID in its request body must verify that the referenced resource belongs to the authenticated user before acting on it. Mismatches return 403 (not 404) because the user is authenticated — they're just not authorized for this specific resource.

The resume endpoint additionally verifies that the paused graph's `user_id` (stored in graph state) matches the JWT's `user_id`; mismatch returns 403.
---

## Acceptance criteria

**Happy path (wine, new-world):**
Given a clear photo of a Beringer 2019 Cabernet Sauvignon from Napa Valley, `POST /items/from-photo` returns a payload with `producer="Beringer"`, `vintage=2019`, `type="red"`, `varietal="Cabernet Sauvignon"` (or close), `region="Napa Valley"`, `country="USA"`, and a non-empty title and description.

**Happy path (wine, old-world monovarietal):**
Given a clear photo of a Chablis Grand Cru wine (no varietal on the label), `POST /items/from-photo` returns a payload with `type="white"`, `varietal="Chardonnay"` (inferred from the appellation, with the description noting the inference), `region="Burgundy"`, `appellation="Chablis Grand Cru"`, `country="France"`, and a non-empty title and description.

**Happy path (wine, Champagne sub-region):**
Given a clear photo of a Champagne bottle labeled with a Côte des Bar producer, `POST /items/from-photo` returns a payload with `type="sparkling"`, `region="Champagne"`, `appellation="Côte des Bar"`, `country="France"`, `varietal=null`, and a non-empty title and description.

**Happy path (Halloween):**
Given a clear photo of a Funko Pop Jack Skellington, `POST /items/from-photo` returns a payload with `manufacturer="Funko"`, `character_or_series="Jack Skellington"` (or close), and a non-empty title and description.

**Happy path (Other):**
Given a photo of a stapler, `POST /items/from-photo` returns a payload with a non-empty title and description.

**Low-confidence handling:**
Given a blurry photo of a Hallmark Halloween ornament where the year stamp is partially obscured, the response includes a low `confidence_scores` value for `year` (and any other affected field). The mobile UI renders low-confidence fields in a distinct color so the user verifies them before saving.

**No-hallucination (extraction):**
Given a wine bottle with no visible vintage on the label, `vintage` is `null`, not a guess. Verified by a test with a fixture image.

**No-hallucination (OCR):**
Given a generic unmarked ceramic pumpkin, the `ocr` node returns empty string with `reason: "no_text"`, not fabricated Halloween text. Given a blurry wine label where text is present but unreadable, `ocr` returns empty string with `reason: "unreadable"`, not guessed text. Both cases verified by adversarial fixtures with `must_not_contain` assertions.

**Auth:**
Two test users see only their own items in `GET /items`. JWT missing or invalid → 401.
User A uploads a photo to `photos/<user-a-id>/<uuid>.jpg`. User B, authenticated with their own JWT, calls `POST /items/from-photo` with User A's storage path. The backend returns 403 without loading the image or running the pipeline. Verified by a test with two test users.

**Resume auth and lifecycle:**
Resuming a paused graph with a JWT whose `user_id` doesn't match the graph state's `user_id` returns 403. Resuming a checkpoint older than 1 hour returns 410. Resuming a graph that has already been resumed returns 409. Verified by tests with two test users and a time-advancing fixture.

**Update:**
An authenticated user can update fields of their own items via `PATCH /items/{id}`. Attempting to update another user's item returns 404. Attempting to change the `category` field returns 400. Verified by tests with two test users.

**Deletion:**
An authenticated user can delete their own items via `DELETE /items/{id}`. Attempting to delete another user's item returns 404 (same response as a non-existent item). After successful deletion, the item no longer appears in `GET /items`. Verified by a test with two test users.
---
