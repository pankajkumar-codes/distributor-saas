"""Number series settings (LLD-1 §4, business.series_settings): each document kind's
prefix, width and first value, and whether the business still issues practice documents
(BH-5). Sales copies a kind's settings into its own series row at the FY's first
finalize (LLD-4 L4-2)."""

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from .frequency import BOUND


@dataclass(frozen=True)
class SeriesSetting:
    kind: str
    prefix: str
    width: int
    first_value: int
    practice_mode: bool


def series_setting(tx: Session, kind: str) -> SeriesSetting | None:
    """The bound business's settings for `kind`, or None when it has none yet (which
    finalize treats as practice mode, BH-5's default)."""
    row = tx.execute(
        text(
            f"select kind, prefix, width, first_value, practice_mode from business.series_settings"
            f" where {BOUND} and kind = :k"
        ),
        {"k": kind},
    ).one_or_none()
    return None if row is None else SeriesSetting(*row)
