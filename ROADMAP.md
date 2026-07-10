# Roadmap

Features considered during MVP planning but deliberately deferred. Each entry describes what, not when. Entries are not commitments — they're a record of decisions made and the reasoning behind them.

## Item location tracking

Rooms and boxes as first-class entities. Items can belong to a box; boxes have QR codes; users can scan a box to see its contents, or look up an item to find where it is stored. Users can pick from default rooms (Garage, Living Room, Wine Cellar, etc.) or define custom ones.

Users can update location over time: change the box an item is in, change the room a box is in, rename a room, rename a box. Box display labels ("Box #7") are not unique — a user can have Box #7 in the garage and Box #7 in the attic. Uniqueness comes from the UUID primary key on each box, which is also what the QR code encodes. Renaming a box does not change its UUID, so existing QR codes continue to work.

Implementation sketch: two new tables (`rooms`, `boxes`), each with UUID primary keys. Two nullable foreign keys on BaseItem (`room_id`, `box_id`). Update endpoints for items (change location), boxes (rename, change parent room), and rooms (rename, delete if empty). QR codes encode the box UUID. A location management UI for rooms and boxes. No changes to the extraction pipeline.

## Parent categories

A second taxonomic layer above the leaf categories for database search and faceted navigation. Wine rolls up to Food; Halloween rolls up to Holiday Decor; future categories like Christmas would also go under Holiday Decor; books might go under Media.

Mostly useful once the inventory has enough variety that flat category filters stop being sufficient. Implementation is a mapping table or a static enum on each leaf category pointing to its parent. No changes to the extraction pipeline.

## Additional item categories

Books, comics, Christmas, kitchenware, etc. Each is a new Pydantic subclass, a new form component, and a new branch in `extract_structured`. Items saved as Other can be reclassified into the new category when it ships — because Other has only BaseItem fields, reclassification is lossless.

## Barcode-based item entry

Alternative input flow where the user scans a barcode (UPC, ISBN) instead of photographing. Looks up canonical metadata from an external source and prefills the form. Separate backend endpoint and separate mobile flow; catalog pipeline unchanged.

Best suited for categories with reliable canonical databases — ISBN for books, UPC for mass-market retail. Less useful for wine (patchy coverage) and mostly useless for Halloween collectibles (no central database).

## Re-run extraction against a different category

If a user realizes they picked the wrong category after save, offer a "re-run extraction" action that runs the extraction node against a different category schema, preserving BaseItem fields (photo, title, description, notes, estimated_value) and filling in the new category-specific fields. MVP uses delete-and-recreate.

## Automated price lookup

External lookup of estimated prices for catalogued items. Wine prices from Wine-Searcher, CellarTracker, or Vivino. Halloween collectible prices from eBay sold-listings or similar aggregators. The user sees a suggested value with source attribution; they can accept it or override with their own estimate.

Architecturally a new enrichment node in the extraction pipeline (or a post-save background job). Per-category provider pattern: each category has its own price provider, since the data sources differ. No pricing provider is universal; some categories (generic Other items) have no sensible source at all.

Real design questions this surfaces: how often to re-query (stale prices mislead), how to handle ambiguous matches (three wines named "Reserve 2019"), whether to show a single number or a range, and what to do when no match is found. MVP sidesteps all of this by keeping `estimated_value` user-entered.

## Automated quality rating lookup

External lookup of ratings for catalogued items. Wine ratings from Wine Spectator, Robert Parker, Vivino community scores. Halloween items typically have no equivalent rating system, but other future categories (books, films) do.

Separate from price lookup because the sources, update cadences, and data models are different. Ratings are more stable than prices (a Beringer 2019 rating doesn't change week to week), which means caching is easier and re-query cadence is much lower.

Shares the per-category provider pattern with price lookup but is a different provider type. A category might have a price provider without a rating provider, or vice versa.

## Prompt caching on the extraction node

Anthropic prompt caching cuts input token cost roughly 90% on cached portions. Category-specific extraction prompts are long and identical across calls, making this a high-leverage optimization. See `EXPERIMENTS.md` X1.

## Desktop batch upload

Desktop web app for uploading many photos at once and working through the extracted drafts in a queue. Same backend, same graph, new mobile-web-compatible frontend and a new `POST /items/batch` endpoint with concurrency capped at 3–5 parallel graph runs.

## OAuth sign-in

Social sign-in (Google, Apple) as an alternative to email+password. Requires Expo deep-link configuration for the redirect flow, which is non-trivial. MVP uses email+password.

## Edit history

`updated_at` on BaseItem captures "when was this last touched," but not what changed or who changed it. A full edit history (field-level diffs, timestamps, maybe a revert) could be valuable for items cataloged over years. Not MVP scope.

## Reclassification workflow for Other items

When a new specific category ships (e.g., Christmas), provide a bulk workflow for the user to browse their Other items and reclassify them into the new category. BaseItem fields carry forward; new category-specific fields are filled by user or by re-running extraction.

## Multi-user sharing

Shared inventories (household, couple, collector groups). Adds a layer of permissions and invitations. Non-trivial UX work around who can edit what. Explicitly out of scope for MVP.

---

Entries are added here when a feature is considered and deliberately deferred. They are not added when a feature is aspirational or speculative. The difference: deferred features have a specific trigger for reconsidering them ("when the catalog has grown past N items," "when users start asking for X," "when a specific customer need emerges"). Aspirational features don't.
