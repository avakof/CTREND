"""CTREND — replication of Fieberg, Liedtke, Poddig, Walker & Zaremba (JFQA 2025).

Package root. See SPEC.md for the authoritative specification and CLAUDE.md for
the invariants (I1-I8) that the test-suite enforces.

M0 ships two things only:
  * ``ctrend.data``   — the Dataset abstraction whose sole access path is
    ``Dataset.asof(week)`` (invariant I1).
  * ``ctrend.signal`` — a real, spec-correct CS-C-ENet core (SPEC §4.3) driven
    entirely through ``Dataset.asof``.
"""

__version__ = "0.1.0"

#: SPEC §4.2 / §4.3 step 4 fix the indicator count at J = 28.
J_INDICATORS = 28
