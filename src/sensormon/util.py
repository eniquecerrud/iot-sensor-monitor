"""Helpers compartidos."""

from __future__ import annotations

import logging
from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)


def setup_logging(level: str) -> None:
    numeric = getattr(logging, level.upper(), None)
    if not isinstance(numeric, int):
        raise ValueError(f"Nivel de log desconocido: {level}")
    logging.basicConfig(
        level=numeric,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
