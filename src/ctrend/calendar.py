"""Week arithmetic — the authority for ambiguity A3 (SPEC §8).

A3: the rebalancing weekday is unstated in the paper; the SPEC default is that
weeks end at the Sunday close and positions are held Monday-Sunday. Every
``Week`` in this codebase is a 0-based integer offset from the first week-ending
Sunday at or after ``sample.start``.

The calendar is built **from configuration, never from the panel's extent**.
Deriving the week grid from the data would leak the sample length into every
week-t computation: with a data-derived calendar, ``last_week`` is a function of
future observations. ``WeekIndex.from_config`` is therefore the only supported
constructor for production use.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Iterator, NewType

import pandas as pd

__all__ = ["Week", "WeekIndex", "WEEKDAYS"]

Week = NewType("Week", int)

#: pandas ``dayofweek`` codes: Monday == 0.
WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


@dataclass(frozen=True, slots=True)
class WeekIndex:
    """A fixed grid of week-ending timestamps.

    ``start``/``end`` come from ``sample.*`` in the config; ``weekday`` from
    ``portfolio.rebalance_weekday`` (A3).
    """

    start: pd.Timestamp
    end: pd.Timestamp
    weekday: str = "sunday"

    def __post_init__(self) -> None:
        if self.weekday not in WEEKDAYS:
            raise ValueError(f"unknown rebalance_weekday {self.weekday!r}")
        if self.end < self.first_close:
            raise ValueError("sample.end precedes the first week close")

    # -- construction -------------------------------------------------------
    @classmethod
    def from_config(cls, cfg) -> "WeekIndex":
        """Build from a :class:`ctrend.config.Config`.

        ``sample.end: null`` (live mode) means "today"; that is a wall-clock
        fact, not a data-derived one, so it introduces no look-ahead.
        """
        end = cfg.sample.end or _dt.date.today()
        return cls(
            start=pd.Timestamp(cfg.sample.start),
            end=pd.Timestamp(end),
            weekday=cfg.portfolio.rebalance_weekday,
        )

    # -- geometry -----------------------------------------------------------
    @property
    def _dow(self) -> int:
        return WEEKDAYS[self.weekday]

    @property
    def first_close(self) -> pd.Timestamp:
        """First week-ending timestamp at or after ``start``."""
        delta = (self._dow - self.start.dayofweek) % 7
        return (self.start + pd.Timedelta(days=int(delta))).normalize()

    def close_ts(self, week: Week) -> pd.Timestamp:
        if week < 0:
            raise ValueError(f"week must be >= 0, got {week}")
        return self.first_close + pd.Timedelta(days=7 * int(week))

    def span(self, week: Week) -> tuple[pd.Timestamp, pd.Timestamp]:
        """Half-open-in-spirit span of week *w*: (close-6d 00:00, close 23:59:59.999999).

        Daily bars are assigned to a week by their own timestamp falling inside
        this span, so a bar can never land in a week earlier than it occurred.
        """
        close = self.close_ts(week)
        lo = close - pd.Timedelta(days=6)
        hi = close + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
        return lo, hi

    def of(self, ts) -> Week:
        """Week containing timestamp ``ts`` (i.e. the week whose close covers it)."""
        ts = pd.Timestamp(ts).normalize()
        if ts < self.first_close - pd.Timedelta(days=6):
            raise ValueError(f"{ts} precedes the calendar start")
        days = (ts - self.first_close).days
        # ceil-divide by 7 so a bar maps forward to its own week's close
        return Week(-((-days) // 7))

    @property
    def last_week(self) -> Week:
        return Week(int((self.end - self.first_close).days) // 7)

    def iter_weeks(self) -> Iterator[Week]:
        for w in range(int(self.last_week) + 1):
            yield Week(w)

    def __len__(self) -> int:
        return int(self.last_week) + 1

    def __contains__(self, week: object) -> bool:
        return isinstance(week, int) and 0 <= week <= self.last_week
