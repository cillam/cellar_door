"""validate -- non-model Pydantic check on extract_structured's output.

See SPEC.md's node contract. On validation failure, blanks only the
invalid fields (not the whole payload), flags them at confidence 0.0,
and records the validation error for the user to see. No retry in the
MVP -- see EXPERIMENTS.md's E3 for the (currently unimplemented) retry
experiment.

In practice, ClaudeProvider's structured-output call already enforces
WineFields/HalloweenFields' constraints (langchain's schema validation
happens before extract_structured ever sees a result), so a failure
here should be rare -- this node is a final consistency guard, not the
primary enforcement point.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.graph.schemas import HalloweenFields, WineFields
from app.graph.state import GraphState

_FIELDS_SCHEMA_BY_CATEGORY: dict[str, type[WineFields] | type[HalloweenFields]] = {
    "wine": WineFields,
    "halloween": HalloweenFields,
}


async def validate(state: GraphState) -> GraphState:
    if state.confirmed_category not in _FIELDS_SCHEMA_BY_CATEGORY:
        # "other" has no category-specific fields to validate.
        return state
    if state.structured_fields is None:
        # extract_structured hasn't run (or was skipped) -- nothing to
        # validate yet.
        return state

    schema = _FIELDS_SCHEMA_BY_CATEGORY[state.confirmed_category]
    try:
        schema.model_validate(state.structured_fields)
    except ValidationError as exc:
        blanked_fields, blanked_confidence = _blank_invalid_fields(state.structured_fields, exc)
        return state.model_copy(
            update={
                "structured_fields": blanked_fields,
                "confidence_scores": {**state.confidence_scores, **blanked_confidence},
                "validation_errors": [*state.validation_errors, str(exc)],
            }
        )
    return state


def _blank_invalid_fields(
    fields: dict[str, Any], exc: ValidationError
) -> tuple[dict[str, Any], dict[str, float]]:
    blanked = dict(fields)
    confidence_updates: dict[str, float] = {}
    for error in exc.errors():
        if not error["loc"]:
            # Root-level error (e.g. `structured_fields` isn't a mapping
            # at all) -- nothing to blank at the field level, so this
            # error is recorded in validation_errors but nothing gets
            # corrected. Assumes structured_fields is always built from
            # an already-validated WineFields/HalloweenFields.model_dump()
            # (true today, in extract_structured.py), so a root-level
            # error shouldn't occur in practice. Revisit if a future
            # provider swap (EXPERIMENTS.md) stops guaranteeing that.
            continue
        field_name = str(error["loc"][0])
        blanked[field_name] = None
        confidence_updates[field_name] = 0.0
    return blanked, confidence_updates
