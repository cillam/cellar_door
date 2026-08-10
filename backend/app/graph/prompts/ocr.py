"""Prompt for the ocr node. See SPEC.md's three-state node contract."""

OCR_PROMPT = """Transcribe any text visible on the item in this photo.

You must return exactly one of three states:

1. "text_present" -- text is visible and readable. Transcribe it
   verbatim: do not summarize, correct spelling, or normalize
   formatting. Return the transcribed text.
2. "text_unreadable" -- text is visible on the item but you cannot read
   it (blurry, occluded, heavily stylized, partial). Return an empty
   string and reason "unreadable". Do NOT guess what the text probably
   says based on the item type or context.
3. "no_text" -- there is no text on the item at all (e.g. a wax seal,
   an embossed-only logo, an unlabeled item). Return an empty string
   and reason "no_text".

Known failure modes:
- The most damaging failure is fabricating plausible-sounding text when
  none exists -- e.g. inventing "CHÂTEAU RÉSERVE 2018" for an unlabeled
  wine bottle, or "HAPPY HALLOWEEN 2023" for a blank ceramic pumpkin.
  If you are not reading actual visible characters, use "no_text" or
  "text_unreadable", never a guess.
"""
