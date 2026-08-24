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

_WINE_SPECIFIC_RULES = """Region vs. appellation:
- `region` is the broad geographic area the wine comes from (Napa
  Valley, Burgundy, Champagne).
- `appellation` is the specific identifier for the wine within its
  region. Populate with either a formal legal designation (AVA, AOC,
  DOCG, DOP) or a widely-recognized sub-region within regions whose
  sub-regions aren't formal appellations (e.g. Champagne's five
  sub-regions: Montagne de Reims, Vallée de la Marne, Côte des Blancs,
  Côte de Sézanne, Côte des Bar).
- When the label shows only a region with no finer subdivision,
  populate `region` and leave `appellation` null.
- Named vineyards, climats, crus, and specific plots (Les Clos,
  Cannubi, To Kalon) do NOT go in `appellation`. Mention them in the
  description instead.

Varietal exception for monovarietal appellations:
- General rule: `varietal` must appear on the label. Do NOT infer
  varietal from producer name, region, or model priors about what
  wineries typically make.
- Exception: some appellations legally require a specific single grape
  variety. For these, populate `varietal` from the appellation even
  when varietal is not printed on the label. Examples include Chablis
  (Chardonnay), Barolo (Nebbiolo), Sancerre (Sauvignon Blanc for
  white, Pinot Noir for red), Brunello di Montalcino (Sangiovese),
  Cornas (Syrah), and Burgundy Grand/Premier Cru wines from the Côte
  d'Or (Chardonnay for whites, Pinot Noir for reds).
- Only apply this exception when the appellation's legal specifications
  require a single specific grape variety. Do NOT apply to
  appellations that permit blends: Bordeaux (all levels), Rioja,
  standard Champagne (without Blanc de Blancs/Noirs designation),
  Côtes du Rhône, or any American AVA (all AVAs permit multiple
  varietals).
- When populating varietal via this exception, add a note to the
  description indicating the source: e.g., "Chardonnay inferred from
  Chablis Grand Cru appellation."
- When uncertain whether an appellation qualifies, leave `varietal`
  null. Null is always the safe answer.

Bottled_in vs. region:
- `bottled_in` is the physical location of the winery that bottled the
  wine, from the "produced and bottled by" line on the label. It is a
  specific city or municipality plus state/country (e.g., "St. Helena,
  California", "Épernay, France").
- Never infer `bottled_in` from `region`. A wine from Napa Valley
  wasn't necessarily bottled in Napa Valley.

Style vs. proprietary names:
- `style` is limited to sweetness/house-style descriptors -- terms
  describing how the wine was made, not what it's called. See the
  field's own examples: Brut, Reserve Brut, Demi-Sec, Dry, Late
  Harvest, Ruby, Tawny.
- A cuvée, special bottling, or proprietary wine name (e.g. "The Lark
  Ascending", "Opus One", "Insignia") is NOT a style, even when it's
  the most prominent text on the label. Leave `style` null and let it
  surface in the description instead -- the same treatment named
  vineyards get under `appellation`.
- When uncertain whether a label term is a sweetness/house-style
  descriptor or a proprietary name, leave `style` null.

Country naming:
- Always use the full country name, never an abbreviation or code --
  "United States", not "USA" or "US". This must be consistent across
  every extraction: a user filtering their collection by country
  needs every wine from the same country to use the identical string.
"""

WINE_EXTRACTION_PROMPT = (
    """Extract the following fields for a bottle of wine, from the photo and
the OCR text below. Return null for any field without direct evidence.

Fields: producer, vintage, type, varietal, style, region, appellation,
country, bottled_in, bottle_size.

Identification (context only, not evidence on its own):
{identify_summary}

OCR result:
{ocr_summary}

"""
    + _EVIDENCE_RULES
    + "\n"
    + _WINE_SPECIFIC_RULES
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
