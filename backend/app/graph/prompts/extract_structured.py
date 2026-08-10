"""Prompts for the extract_structured node. See SPEC.md's node contract.

Two full prompts (wine, halloween) rather than one shared template with
the field list swapped in -- the fields genuinely differ per category,
and duplicating the evidence-discipline rules keeps each prompt
readable on its own rather than needing to be read alongside a
field-list lookup.
"""

_EVIDENCE_RULES = """Only populate a field if you have direct evidence for it:
- Visible text on the label/item itself, OR
- A deterministic inference from visible text (e.g. a region that
  uniquely determines a country).

identify's best guess (given below) may tell you what to look for, but
is never sufficient evidence on its own -- "probably a Beringer
Cabernet" does not populate producer="Beringer" unless "Beringer"
actually appears in the OCR text or is clearly visible on the label.

Numeric fields must be backed by the OCR text: either the digits appear
verbatim, or the value is deterministically derivable from text that
does appear (e.g. "Nineteen Ninety-Nine" -> 1999). If a numeric value
isn't supportable either way, it is null -- regardless of how confident
you feel about it.

If you cannot find evidence for a field, set it to null and its
confidence to 0.0 -- never null confidence for a null field, and never
a guessed value paired with a confidence you don't believe.

Known failure modes:
- Populating a field from identify's guess alone, with no label
  evidence.
- A stylized/ornate numeral being misread as a vintage/year when it
  isn't one, or invented when no vintage/year is visible at all.
"""

WINE_EXTRACTION_PROMPT = (
    """Extract the following fields for a bottle of wine, from the photo and
the OCR text below. Return null for any field without direct evidence.

Fields: producer, varietal, vintage, region, country, bottle_size.

Identification (context only, not evidence on its own):
{identify_summary}

OCR result:
{ocr_summary}

"""
    + _EVIDENCE_RULES
)

HALLOWEEN_EXTRACTION_PROMPT = (
    """Extract the following fields for a Halloween collectible, from the
photo and the OCR text below. Return null for any field without direct
evidence.

Fields: manufacturer, character_or_series, year, edition. Do not
populate `condition` -- that's a user judgment call, not a visual-AI one.

Identification (context only, not evidence on its own):
{identify_summary}

OCR result:
{ocr_summary}

"""
    + _EVIDENCE_RULES
)
