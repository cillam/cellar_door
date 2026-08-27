# Cellar Door — Frontend Kickoff Prompt

You are Claude Code working on the Cellar Door project. The backend is complete and deployed. Today's goal is the Expo mobile app that consumes it.

Before doing anything else, read the following files in this order:

1. `CLAUDE.md` — governance, tech stack, conventions, agent workflow
2. `SPEC.md` — the product spec, especially the API contract, streaming semantics, WineItem schema (recently expanded — see below), and acceptance criteria
3. `README.md` — repo overview
4. Any files under `.claude/` that describe skills you should know about

Then read the backend code to understand what you're consuming:

- `backend/app/main.py` — endpoint definitions
- `backend/app/models/items.py` — Pydantic schemas (this is what the mobile forms must match)
- `backend/app/routers/items.py` (or wherever endpoint handlers live) — the exact request/response shapes

## Context from backend work

The backend build is complete. All seven endpoints from SPEC.md are implemented and deployed to Railway. Supabase Auth, Storage, and Postgres are wired. LangGraph pipeline runs against real Claude for all five nodes. The deployed backend has been smoke-tested end-to-end with a real wine photo.

**Schema change during backend work:** WineItem was expanded from 6 fields to 10 based on real-item testing that surfaced the schema couldn't accommodate Champagne or old-world wines. The current schema:

```
producer, vintage, type, varietal, style, region, appellation,
country, bottled_in, bottle_size
```

The frontend WineForm must match this. HalloweenItem and OtherItem are unchanged from SPEC.md's original definition.

These values live in my env file outside the repo (same pattern as the backend build). The variables the mobile app needs:

- `EXPO_PUBLIC_BACKEND_URL` — the Railway domain
- `EXPO_PUBLIC_SUPABASE_URL` — the Supabase project URL (same value as the backend's `SUPABASE_URL`)
- `EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY` — the `sb_publishable_...` key (NOT the secret key; publishable is safe for client-side use, secret is backend-only)

Wire the mobile app to read them from an env file path specified by an environment variable (e.g., `CELLAR_DOOR_MOBILE_ENV_FILE`), with a fallback to `mobile/.env` for convenience. I'll export the env var in my shell before running Expo commands, so the app reads from my safe location. For EAS builds, I'll set them via `eas secret:create` using the same values.

Never hardcode any of these values in code. `.env.example` should document the expected variable names with placeholder values only.

The mobile app authenticates users via Supabase Auth using the publishable key, then passes the resulting JWT to the backend as a Bearer token.

## Governance rules (from CLAUDE.md)

Before you start, understand what you can and cannot do:

- **You do not edit `SPEC.md`, `CLAUDE.md`, `README.md`, or any file under `.claude/` without my explicit approval.** If you think one needs to change, propose the change and wait for me to apply it myself.
- **You do not commit directly to `main`.** All work goes through PRs. The PR review workflow will automatically comment on your PRs.
- **You use `uv` for Python and `npm` for JavaScript, per CLAUDE.md.** Do not switch package managers.
- **You do not add dependencies without proposing them first.** New packages introduce security, licensing, and maintenance considerations I want to review.
- **You do not run destructive commands (`rm -rf`, `git push --force`, `git reset --hard` on main) without explicit approval per command.**

## Today's steps

Work through these in order. After each step, open a PR titled `Step N: <description>` (e.g., "Step 1: Expo scaffold"). Wait for me to review and merge before starting the next step.

### Step 1: Expo scaffold

Scaffold the Expo app in `mobile/` (sibling to `backend/`). Use:

- Expo SDK (current stable)
- TypeScript with strict mode
- `expo-router` for navigation
- `expo-camera` for photo capture
- `@supabase/supabase-js` for auth and storage upload

Set up:

- `mobile/tsconfig.json` with strict mode
- `mobile/app.json` or `app.config.ts` with basic app metadata
- `mobile/.env` handling via `EXPO_PUBLIC_*` env vars — hardcode nothing
- `.env.example` documenting the expected variables
- Basic routing structure: `app/(auth)/login.tsx`, `app/(tabs)/index.tsx` (inventory), `app/(tabs)/add.tsx` (add item flow), `app/item/[id].tsx` (item detail)
- Placeholder screens that just render the screen name, so navigation can be verified before real UI

Do NOT do UI polish yet. The goal of step 1 is a working navigation shell with the right file structure.

Propose the file structure before writing code. Wait for my approval.

### Step 2: Auth

Implement email/password authentication using Supabase Auth.

- Login screen: email + password fields, sign-in button, sign-up link
- Sign-up screen: email + password, confirm password, sign-up button
- Session persistence: user stays signed in across app restarts
- Sign-out button somewhere in the tab navigator (settings screen is fine)
- Loading and error states for both auth actions
- On successful auth, navigate to the inventory tab

Test with the two test users I created in Supabase (`test-user-a@cellar-door.dev` and `test-user-b@cellar-door.dev`).

### Step 3: Camera capture

Implement the camera screen in `app/(tabs)/add.tsx`.

- Request camera permission on mount; show a clear "camera access required" screen if denied
- Full-screen camera preview
- Capture button (large, tap-friendly)
- After capture: preview the photo with retake/confirm buttons
- On confirm: navigate to the pipeline progress screen (implemented in step 5)

Photo should be captured at reasonable quality (not maximum — target ~2-4MB per photo to keep upload fast).

### Step 4: Upload to Supabase Storage

Implement the upload flow.

- Generate a UUID for the photo filename
- Upload to `photos/{user_id}/{uuid}.jpg` in the `photos` bucket
- Handle upload progress and errors
- On success, return the storage path so it can be passed to the backend

Verify: after upload, the file should be visible in the Supabase Storage dashboard.

### Step 5: Pipeline progress screen with SSE

This is the most complex step. Implement the screen that receives the SSE stream from the backend.

- Call `POST /items/from-photo` with the storage path in the request body and the JWT in the Authorization header
- Parse the SSE stream and render per-node updates as they arrive
- The stream will close after `await_category` — show a category confirmation UI at that point
- On category confirmation, call `POST /items/from-photo/{thread_id}/resume` with the user's category choice
- Parse the second SSE stream from resume through `complete`
- On `complete`, navigate to the prefilled form (step 6)

SSE parsing in React Native is non-trivial — you may need `react-native-sse` or an equivalent. Propose the library choice before adding.

Progress UI: show each node as it completes. Something like:
- ✓ Category identified (wine, 94%)
- (User confirms category)
- ⋯ Identifying...
- ⋯ Reading text...
- ✓ Description generated
- ⋯ Extracting details...
- ✓ Done

### Step 6: Prefilled form with category variants

Implement the form screen that displays the pipeline result and lets the user edit before saving.

Three form variants keyed on category:

**WineForm** (10 fields per current SPEC.md):
- producer (text)
- vintage (number, optional)
- type (dropdown: red / white / rose / sparkling / dessert / fortified)
- varietal (text)
- style (text)
- region (text)
- appellation (text)
- country (text)
- bottled_in (text)
- bottle_size (text, e.g., "750ml")

**HalloweenForm** (5 fields):
- manufacturer
- character_or_series
- year (number)
- edition (dropdown: limited / standard)
- condition (dropdown: mint / good / fair / poor)

**OtherForm:**
- No category-specific fields (base fields only)

All variants show base fields: title, description, notes, estimated_value.

**Low-confidence highlighting:** for each field, look up its confidence from the `confidence_scores` dict in the pipeline result. Fields with confidence < 0.5 render in a distinct color (amber or similar) so the user knows to verify them.

**Save action:** on save, `POST /items` with the completed payload. Navigate to the item detail screen on success.

### Step 7: Inventory list

Implement `app/(tabs)/index.tsx` — the user's inventory list.

- Fetch from `GET /items` on mount
- Display each item as a card: thumbnail (from photo_url), title, category badge, vintage/year if applicable
- Sorted newest first (matches backend default)
- Pull-to-refresh
- Empty state ("No items yet — tap Add to catalog your first one")
- Loading and error states
- Tap an item to navigate to `app/item/[id].tsx`

### Step 8: Item detail

Implement `app/item/[id].tsx` — single item view.

- Fetch from `GET /items/{id}` on mount
- Display all fields (base + category-specific) in a readable layout
- Show the photo
- Edit button navigates to a pre-populated form screen (reuse the form components from step 6, but with the existing item's values)
- Delete button with confirmation dialog — calls `DELETE /items/{id}`, navigates back to the inventory list on success

For edit: on save, `PATCH /items/{id}` with only the changed fields.

### Step 9: Real device testing

Non-negotiable. Do not skip.

Before EAS builds, install Expo Go on a physical device (iOS and Android if possible), scan the dev QR code, and verify the full happy path works on the real device:

1. Sign up as a new user
2. Take a photo of a real item (physical wine bottle or similar)
3. Watch the pipeline progress in real time
4. Confirm category, wait for extraction to complete
5. Verify the form is prefilled correctly
6. Save the item
7. Verify it appears in the inventory list
8. Tap it, see detail view
9. Edit a field, save, verify the change persists
10. Delete it, verify it's gone

Real device testing catches things simulator testing cannot: real camera behavior, real network latency, real touch targets, real keyboard interactions.

If anything is broken, fix it before moving on. Do not skip to EAS build with a broken app.

### Step 10: EAS Android build

Configure EAS Build for Android internal distribution.

- Install `eas-cli` if not present
- Run `eas build:configure`
- Configure `eas.json` with a `preview` profile for internal distribution
- Set env vars via `eas secret:create` (mirror what's in `.env`, but with `EXPO_PUBLIC_` prefix for anything the client needs)
- Run `eas build --platform android --profile preview`
- Wait for build to complete (~20 min)
- Get the APK download link from the EAS dashboard

Test the APK install on a real Android device that isn't the one you developed on. This catches env var issues, permission issues, and things that only work in dev mode.

### Step 11: iOS via Expo Go

Since we're not paying the $99 Apple Developer fee, iOS distribution is via Expo Go:

- Publish an update: `eas update --branch preview --message "portfolio demo build"`
- Verify the update is accessible: install Expo Go on an iPhone, scan the QR code from the EAS dashboard, verify the app loads and works
- Document the QR code URL / install path so it can be shared with interviewers

### Step 12: Ready-for-demo checklist

Before calling frontend done:

- The Android APK installs and runs on a device other than the dev device
- The Expo Go QR code loads the app on an iPhone
- Both installations can sign in as a test user, take a photo, get a prefilled form, save an item, see it in inventory
- All three category paths (wine, halloween, other) have been tested with real photos
- At least one adversarial case has been tested (blurry photo, no-label item, or unusual category)
- The Railway backend is still running and responsive

## Notes on the WineForm specifically

The 10-field WineForm is denser than the other categories. Think about mobile UX:

- Group related fields visually (identity: producer + vintage + varietal; classification: type + style; geography: region + appellation + country + bottled_in; physical: bottle_size)
- Consider collapsible sections if the form feels too tall
- Type field is a Literal (red/white/rose/sparkling/dessert/fortified) — use a dropdown or segmented control, not free text
- All fields are optional (nullable) — don't require any to save; the user might catch things the model missed and want to save partial data

## What to do next

Start by proposing the file structure for step 1. Do not write any code yet — I want to review the structure before you start implementing.

When you're ready, propose the structure and wait for approval.
