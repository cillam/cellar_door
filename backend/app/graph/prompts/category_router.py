"""Prompt for the category_router node. See SPEC.md's node contract."""

CATEGORY_ROUTER_PROMPT = """You are classifying a single item from a photo into one of three
categories: "wine", "halloween", or "other".

Look only at the item itself -- its shape, material, markings, and any
visible text. Do not classify based on background objects or the
surrounding scene; only the item in focus matters.

Return "other" whenever the item is not clearly a bottle of wine or a
Halloween-themed collectible/decoration. When in doubt, prefer "other"
over a confident-sounding wrong guess.

Provide a confidence score in [0.0, 1.0] reflecting how certain you are
in the category itself, not in any other detail about the item.

Known failure modes:
- Ambiguous items (e.g. a wine-themed Halloween decoration) should get
  the category you judge most likely, with confidence reflecting the
  ambiguity -- not an artificially high or low score to hedge.
"""
