# Skill: Process a new eval fixture

You assist with the mechanical parts of adding an eval fixture. The human photographs the item, writes the ground truth, and decides what makes the fixture worth adding. You handle file processing, scaffolding, and the baseline eval run.

You never edit ground truth values. If the human asks you to populate a ground truth field, decline and ask them to provide the value.

## When invoked

The human gives you one or more of:
- A raw photo to process
- A populated ground truth JSON
- A request to run the baseline eval against a new fixture

Do only what's asked. Don't infer additional steps unless explicitly told.

## What you do

### Image processing

When given a raw photo:
1. Resize to ~1600px on the long edge, preserving aspect ratio
2. Re-encode as JPEG at quality 0.85
3. Save to `backend/evals/fixtures/<category>_<descriptive_name>.jpg` with the name the human specifies (or ask if they didn't)
4. Confirm the output path back to the human

### JSON scaffolding

When asked to scaffold a ground truth JSON:
1. Create a sibling file at `backend/evals/fixtures/<same_stem>.json`
2. Use the appropriate template (standard or adversarial — ask if unclear)
3. Leave all value fields empty or as `null` placeholders — do not populate
4. Confirm the file is ready for the human to fill in

Templates:

Standard fixture:
```json
{
  "category": "",
  "identify": {
    "best_guess": "",
    "acceptable_alternatives": []
  },
  "ocr": {
    "state": "text_present",
    "must_contain": [],
    "must_not_contain": []
  },
  "extract_structured": {},
  "notes": ""
}
```

Adversarial fixture (no text or unreadable label):
```json
{
  "category": "",
  "identify": {
    "best_guess": "",
    "acceptable_alternatives": []
  },
  "ocr": {
    "state": "no_text",
    "reason": "no_text",
    "must_contain": [],
    "must_not_contain": []
  },
  "extract_structured": {},
  "notes": ""
}
```

The `extract_structured` shape depends on category — leave it as an empty object and let the human populate it.

### Running the baseline

When asked to run the baseline against a new fixture:
1. Run `python -m evals.runners.full_pipeline --fixture <fixture_stem>`
2. Save the report to `backend/evals/reports/` with a timestamped filename
3. Commit the report with a clear message
4. If the run failed against the fixture, report this clearly. Do not modify the fixture or the pipeline to make it pass — the human decides what to do next.

### Pre-merge checks

When asked to verify a fixture is ready for merge, confirm:
- Image and JSON files exist as siblings with matching stem names
- Naming follows `<category>_<descriptive_name>` convention
- JSON parses as valid JSON
- Baseline eval report exists in `evals/reports/` for this fixture

Report any issues. Do not fix them.

## What you don't do

- Edit ground truth values
- Decide what `must_not_contain` should include
- Write the `notes` field
- Photograph items
- Tweak the pipeline to make a failing baseline pass
- Add new fixtures unprompted