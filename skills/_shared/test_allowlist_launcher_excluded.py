"""Regression (PR #360 review, round 1): no shipped allow rule admits the pushing launcher.

`launch_design_run.py` commits the seat brief and pushes `tp/<slug>`, and `--brief FILE`
(also the argparse abbreviation `--bri`) takes any local path as the brief content. A narrow
rule skips the classifier for any argument, so no deny glob can close this: the launcher and
the two pro scripts that reach it (`fleet_roster.py add --brief`, `fleet_churn_watch.py`)
must not be on the list at all (the two pro scripts: `test_exclusions_absent`).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import allowlist_rules  # noqa: E402
import allowlist_settings as st  # noqa: E402

ROOT = Path(st.__file__).resolve().parents[2]
Q = chr(34)
LAUNCH = "python3 " + Q + "$TP_ROOT" + Q + "/skills/_shared/launch_design_run.py demo "


def _admitted(text):
    rec = st.load()
    allow = st.expand(st.entries_for(rec, "github", ROOT), st.root_forms(ROOT, None), [])
    deny = st.deny_rules(rec)
    hit = [r for r in allow if allowlist_rules.rule_matches(r, text)]
    denied = any(allowlist_rules.rule_matches(r, text) for r in deny)
    return hit if hit and not denied else []


def test_no_shipped_allow_rule_admits_the_pushing_launcher_with_a_brief():
    for text in (LAUNCH + "--brief /etc/hostname", LAUNCH + "--bri /etc/hostname"):
        assert not _admitted(text), text
