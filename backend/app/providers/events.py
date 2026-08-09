"""Usage events emitted by every ModelProvider call.

Structured (JSON) log events rather than free-text logs, so the eval
harness (`backend/evals/`) can parse them directly into per-node cost,
latency, and accuracy reports. See CLAUDE.md's `ModelProvider` conventions.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from pydantic import BaseModel, Field

logger = logging.getLogger("app.providers.usage")


class UsageEvent(BaseModel):
    """One model call's cost/latency accounting, keyed by node."""

    node_name: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    estimated_cost_usd: float
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


def emit_usage_event(event: UsageEvent) -> None:
    """Log a usage event as a single JSON line.

    A standalone function (not a method on the provider) so tests and the
    eval harness can both hook it without caring which provider emitted
    the event.
    """
    logger.info(event.model_dump_json())
