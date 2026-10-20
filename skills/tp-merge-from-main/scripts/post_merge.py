#!/usr/bin/env python3
"""post_merge.py — the driver's post-merge passes, in one call and one order.

design: basesync-count-line-and-low-headroom (2.4)

`merge_back` ends its resolve loop with a post-merge pass over the report, and by now there are two:
the B3 hard-cap backstop (roll or split a doc the merge pushed over its cap) and the 2.4 count check
(defer a `known_issues.md` whose merged Low count does not match the merged Low doc). They are in
this order on purpose: a Low-part SPLIT keeps every `### L` heading, so the count check that runs
after it counts the split parts and still sees the number the merge computed. Swapping the order
would have the count check read an over-cap part the backstop was about to split.

The seam exists so `merge_driver.py` stays at one post-merge call line. Both passes already swallow
their own failures, so nothing here wraps them again.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hardcap_backstop import apply_hard_cap_backstop  # noqa: E402
from low_count_check import apply_low_count_check  # noqa: E402


def apply_post_merge_passes(repo, report) -> None:
    """Hard-cap backstop first (a split keeps the count), then the Low count check."""
    apply_hard_cap_backstop(repo, report)
    apply_low_count_check(repo, report)
