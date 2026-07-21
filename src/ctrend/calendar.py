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

__all__ = ["Week", "WeekIndex", "LiuYearBlockIndex", "WEEKDAYS"]

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
    def from_config(cls, cfg):
        """Build from a :class:`ctrend.config.Config`.

        ``sample.end: null`` (live mode) means "today"; that is a wall-clock
        fact, not a data-derived one, so it introduces no look-ahead.

        GT-1: under ``rebalance_weekday: liu_year_blocks`` this returns a
        :class:`LiuYearBlockIndex` instead — a different calendar geometry, not a
        different phase of the same one.
        """
        end = cfg.sample.end or _dt.date.today()
        if cfg.portfolio.rebalance_weekday == "liu_year_blocks":
            return LiuYearBlockIndex(
                start=pd.Timestamp(cfg.sample.start), end=pd.Timestamp(end)
            )
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


class LiuYearBlockIndex:
    """GT-1 — the authors' actual weekly calendar. There is no rebalancing weekday.

    `b02CalculateIndicators.m:16` sets `lResampleLiuEtAl = true`, so the baseline
    resampler is `Utils/fResampleLiuEtAl.m:53-89`, which ignores weekdays entirely
    and slices each **calendar year** into fixed 7-day blocks counted from that
    year's first day:

      * week 1 of year Y = Jan 1-7; week 2 = Jan 8-14; ...
      * every year has exactly **52** weeks (`fix(365/7)`), and
      * **week 52 absorbs the remainder** -- 8 days, or 9 in a leap year.

    Because the count restarts every January 1, the weekday on which a week ends
    **drifts by 1-2 days each year**. Weeks end Wednesday in 2015, Thursday in
    2016, and so on. Any implementation anchored to a fixed weekday reproduces a
    different partition of the sample, which is why A3's "weeks end Sunday"
    default changed every observation.

    Week IDs are `YYYYWW` integers -- the same convention as the shipped
    `Results/CTREND/CTREND.xlsx`, whose first row is 201516. :meth:`week_id`
    exposes them so a reconstruction can be joined to that series directly.

    The sequential :class:`Week` index used elsewhere in the codebase is simply
    the 0-based position of a block within ``[start, end]``.
    """

    __slots__ = ("start", "end", "_starts", "_ends", "_ids")

    WEEKS_PER_YEAR = 52

    def __init__(self, start: pd.Timestamp, end: pd.Timestamp) -> None:
        self.start = pd.Timestamp(start).normalize()
        self.end = pd.Timestamp(end).normalize()
        if self.end < self.start:
            raise ValueError("sample.end precedes sample.start")

        starts: list[pd.Timestamp] = []
        ends: list[pd.Timestamp] = []
        ids: list[int] = []
        for year in range(self.start.year, self.end.year + 1):
            jan1 = pd.Timestamp(year=year, month=1, day=1)
            dec31 = pd.Timestamp(year=year, month=12, day=31)
            for k in range(1, self.WEEKS_PER_YEAR + 1):
                lo = jan1 + pd.Timedelta(days=7 * (k - 1))
                # Week 52 runs to year end, so it is 8 days long (9 in a leap year).
                hi = dec31 if k == self.WEEKS_PER_YEAR else lo + pd.Timedelta(days=6)
                if hi < self.start or lo > self.end:
                    continue
                starts.append(lo)
                ends.append(hi)
                ids.append(year * 100 + k)
        if not starts:
            raise ValueError("no Liu week blocks intersect the sample range")
        self._starts = tuple(starts)
        self._ends = tuple(ends)
        self._ids = tuple(ids)

    # -- geometry -----------------------------------------------------------
    @property
    def first_close(self) -> pd.Timestamp:
        return self._ends[0]

    def close_ts(self, week: Week) -> pd.Timestamp:
        w = int(week)
        if w < 0 or w >= len(self._ends):
            raise ValueError(f"week {week} outside the calendar")
        return self._ends[w]

    def span(self, week: Week) -> tuple[pd.Timestamp, pd.Timestamp]:
        w = int(week)
        if w < 0 or w >= len(self._starts):
            raise ValueError(f"week {week} outside the calendar")
        hi = self._ends[w] + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
        return self._starts[w], hi

    def week_id(self, week: Week) -> int:
        """`YYYYWW`, matching the shipped CTREND.xlsx convention."""
        w = int(week)
        if w < 0 or w >= len(self._ids):
            raise ValueError(f"week {week} outside the calendar")
        return self._ids[w]

    def of(self, ts) -> Week:
        """Week block containing ``ts``."""
        ts = pd.Timestamp(ts).normalize()
        if ts < self._starts[0]:
            raise ValueError(f"{ts} precedes the calendar start")
        # Blocks are contiguous and ordered, so a right-side bisect on the ends
        # lands on the first block whose end is >= ts.
        import bisect

        idx = bisect.bisect_left(self._ends, ts)
        if idx >= len(self._ends):
            raise ValueError(f"{ts} follows the calendar end")
        return Week(idx)

    @property
    def last_week(self) -> Week:
        return Week(len(self._starts) - 1)

    def iter_weeks(self) -> Iterator[Week]:
        for w in range(len(self._starts)):
            yield Week(w)

    def __len__(self) -> int:
        return len(self._starts)

    def __contains__(self, week: object) -> bool:
        return isinstance(week, int) and 0 <= week < len(self._starts)
