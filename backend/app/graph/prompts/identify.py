"""Prompt for the identify node. See SPEC.md's node contract."""

IDENTIFY_PROMPT = """Identify the specific item shown in this photo as precisely as you can
from what's visible -- brand, product line, character, edition, etc.

Provide a confidence score in [0.0, 1.0] reflecting how certain you are
of your best guess.

If your confidence would be below 0.5, do not give a specific-but-uncertain
guess (e.g. "possibly a Beringer Cabernet"). Instead, describe the item
generically, grounded only in what you can actually see (e.g. "a tall
dark green wine bottle" or "a small ceramic figurine of a cartoon
ghost"). Specificity implies confidence -- hedge by lowering the
confidence score, not by prefacing a specific guess with "possibly" or
"likely".

Known failure modes:
- Do not let a specific guess and a low confidence score coexist. If
  you're not sure, both the text and the score should reflect that.
"""
