"""Prompt for the generate_description_and_title node.

See SPEC.md's node contract. Text-only -- this node synthesizes from
`identify`'s and `ocr`'s already-collected output rather than looking at
the image again, so the prompt is a template filled in with those
results at call time (see app/graph/nodes/generate_description_and_title.py).
"""

GENERATE_DESCRIPTION_AND_TITLE_PROMPT = """Write a short title and a one-paragraph description
for an item, based only on the evidence below. Do not invent anything
beyond what's given here.

Identification (best guess, not guaranteed correct):
{identify_summary}

OCR result:
{ocr_summary}

Produce:
- title: a short display name, five words or fewer.
- description: one paragraph of prose describing the item.

Rules:
- If OCR text is present, you may incorporate it verbatim into the
  description; the title may reference it but doesn't need to quote it.
- If OCR found no text or couldn't read it, describe the item from
  visual/identification evidence only -- do not reference or invent
  label text.
- Stay within what the identification evidence supports. Do not add
  provenance, age, origin, or specificity beyond what's given above.

Known failure modes:
- Fabricating label text when OCR reported no_text or text_unreadable.
- Adding specific claims (a producer, a year, a place) that neither the
  identification nor the OCR evidence actually supports.
"""
