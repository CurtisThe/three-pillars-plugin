"""Doc pin: Tier 1 provisions every run; Tier 5, Tier 7 and Cleanup run the failing scratch check.

Design: run-scratch-in-fence, Task 1.7 (Behaviors 1, 5 and 6). The pins read the
`scratch_leftovers.py` command lines out of the four texts and run them against a fake
run dir, so the text cannot drift from the CLI (skills/_shared/test-fragility.md: the
assertions name the contract words, not the surrounding prose).

Run with: pytest skills/_shared/test_run_scratch_gates_doc.py -q
"""
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import scratch_leftovers as sl  # noqa: E402

SHARED = Path(__file__).resolve().parent
RUN = SHARED.parent / "tp-run-full-design"
FILES = {n: RUN / n for n in ("tier-1-pickup.md", "tier-5-closeout.md", "tier-7-review.md", "SKILL.md")}
CMD = re.compile(r'`python3 "\$TP_ROOT"/skills/_shared/scratch_leftovers\.py ([^`]+)`')
SLUG = "demo-slug"
CAPS = {"tier-1-pickup.md": 25_000, "tier-5-closeout.md": 25_000, "tier-7-review.md": 25_000, "SKILL.md": 35_000}


def text(name):
    return FILES[name].read_text(encoding="utf-8")


def commands(name):
    return [m.group(1) for m in CMD.finditer(text(name))]


def section(body, head):
    start = body.index(head)
    end = body.find("\n## ", start + 1)
    sub = body.find("\n### ", start + 1)
    ends = [e for e in (end, sub) if e != -1]
    return body[start:min(ends)] if ends else body[start:]


def of(name, verb):
    return [c for c in commands(name) if c.split()[0] == verb]


class Fx:
    def __init__(self, root, capsys, monkeypatch):
        self.capsys = capsys
        self.home, self.wt = root / "home", root / "wt"
        self.areas = tuple(str(root / n) for n in ("tmp", "vartmp", "shm"))
        for d in (self.home, self.home / "t", self.wt, *map(Path, self.areas)):
            d.mkdir(parents=True)
        subprocess.run(["git", "init", "-q"], cwd=self.wt, check=True)
        self.env = {"HOME": str(self.home), "CLAUDE_CONFIG_DIR": str(self.home / ".claude")}
        monkeypatch.chdir(self.wt)  # the gate commands run from the worktree: no path argument

    def run(self, args):
        argv = shlex.split(args.replace("{slug}", SLUG))
        rc = sl.main(argv, env=self.env, areas=self.areas)
        return rc, self.capsys.readouterr().out


@pytest.fixture
def fx(tmp_path, capsys, monkeypatch):
    return Fx(tmp_path, capsys, monkeypatch)


GATES = ["tier-5-closeout.md", "tier-7-review.md", "SKILL.md"]


def test_tier1_provisions_every_run_before_outcomes():
    body = text("tier-1-pickup.md")
    sec = section(body, "### Scratch provision")
    assert "Mode A, B and C" in sec and "whatever its env" in sec
    assert of("tier-1-pickup.md", "provision") and sec.index("scratch_leftovers.py provision") >= 0
    assert body.index("### Scratch provision") < body.index("### Tier 1 outcomes")
    assert "[tp-run-full-design/tier-1] scratch-provisioned <run dir>" in sec
    assert "printed path" in sec and "` late`" in sec and "`created`" in sec
    assert sec.index("printenv TMPDIR") < sec.index("scratch-redirect-missing")


def test_tier5_has_one_step_ahead_of_full_step_1_and_light_dispatch():
    body = text("tier-5-closeout.md")
    sec = section(body, "### Step 0")
    assert body.count("scratch_leftovers.py check --expect") == 1
    assert sec.index("scratch_leftovers.py provision") < sec.index("scratch_leftovers.py check --expect")
    assert body.index("### Step 0") < body.index("### Step 1 — Regression check")
    assert body.index("### Step 0") < body.index("### Light and just-do-it closeout")
    assert "every class" in sec and "light" in sec
    assert "exit 1" in sec and "finalizer first" in sec


def test_late_provision_is_logged_not_stopped_on_no_run_scratch():
    for name in GATES:
        body = text(name)
        assert "scratch-provisioned-late" in body, name
        assert "`created`" in body, name
    assert "no run scratch" in section(text("tier-5-closeout.md"), "### Step 0")
    for name in ("tier-7-review.md", "SKILL.md"):
        body = text(name)
        assert body.index("scratch_leftovers.py provision") < body.index("scratch_leftovers.py check --expect"), name


def test_tier7_checks_immediately_before_every_converge():
    body = text("tier-7-review.md")
    step1 = section(body, "### Step 1")
    calls = [m.start() for m in re.finditer(r"converge\.py --round-dir R", step1)]
    assert calls
    for at in calls:
        assert "check --expect --slug {slug}" in step1[max(0, at - 700):at]
    assert "no converge, no ping" in step1 and "finalizer first" in step1


def test_cleanup_runs_check_before_the_terminal_entry_and_keeps_status():
    body = text("SKILL.md")
    sec = body[body.index("\n## Cleanup"):]
    at = sec.index("check --expect --slug {slug}")
    assert at < sec.index("terminal decisions.md entry")
    step = next(ln for ln in sec.splitlines() if "check --expect" in ln)
    assert "scratch-leftover:" in step and "terminal" in step
    assert "tp:needs-human-attention" in step and "when one exists" in step
    assert "stop report" in step and "exit status" in step and "non-zero" in step
    for word in ("fail-open", "|| true", "ignore"):
        assert word not in step


def test_accept_is_the_finalizers_or_the_operators_after_inspection():
    body = text("tier-5-closeout.md")
    assert "accept --path P --reason R" in body
    sentence = next(s for s in re.split(r"(?<=\.)\s", body) if "accept --path P --reason R" in s).lower()
    assert "only the finalizer or the operator" in sentence
    assert "after inspecting the path" in sentence and "decisions.md" in sentence
    for name in FILES:
        if name != "tier-5-closeout.md":
            assert "scratch_leftovers.py accept" not in text(name), name


@pytest.mark.parametrize("name", FILES)
def test_every_gate_command_passes_slug_and_no_path(name):
    body = text(name)
    assert body.count("scratch_leftovers.py") == len(commands(name)) >= 1, name
    for args in commands(name):
        assert "--slug {slug}" in args, args
        if args.split()[0] in ("provision", "check"):
            assert "--worktree" not in args and "--path" not in args, args


@pytest.mark.parametrize("name", FILES)
def test_provision_line_prints_the_run_dir_then_exists(fx, name):
    assert (SHARED / "scratch_leftovers.py").is_file()
    (args,) = of(name, "provision")
    rc, out = fx.run(args)
    assert rc == 0 and str(fx.wt.resolve() / ".tp-scratch" / "run") in out and "created" in out
    rc, out = fx.run(args)
    assert rc == 0 and "exists" in out


@pytest.mark.parametrize("name", GATES)
def test_check_expect_line_exits_0_clean_and_1_with_a_planted_leftover(fx, name):
    (prov,), (chk,) = of(name, "provision"), of(name, "check")
    assert chk.split()[:2] == ["check", "--expect"]
    assert fx.run(prov)[0] == 0
    rc, out = fx.run(chk)
    assert rc == 0 and "scratch-leftover" not in out
    stray = fx.home / ".cache_tel11.json"
    stray.write_text("{}", encoding="utf-8")
    rc, out = fx.run(chk)
    assert rc == 1 and f"scratch-leftover: {stray}" in out


@pytest.mark.parametrize("name", FILES)
def test_text_stays_under_its_char_cap(name):
    assert len(text(name)) < CAPS[name], name


def test_tier6_pr_body_lists_every_scratch_allowed_line():
    body = (RUN / "tier-6-pr.md").read_text(encoding="utf-8")
    line = next(ln for ln in body.splitlines() if "scratch-allowed:" in ln)
    assert line.startswith("- PR description:") and "accepted <date> <reason>" in line
    assert "Tier 5" in line and "Tier 7" in line
    assert len(body) < 25_000


def test_light_and_just_do_it_slot_mappings_run_tier5_step_0_first():
    body = text("SKILL.md")
    for head in ("### Light slot mapping", "### Just-do-it slot mapping"):
        sec = section(body, head)
        assert "tier-5-closeout.md" in sec and "Step 0 first" in sec, head


def test_pr_iterate_checks_before_every_converge():
    pr = RUN.parent / "tp-pr-iterate"
    carried = (pr / "convergence-rules.md").read_text(encoding="utf-8")
    at = carried.index("**Carried** (exit 0)")
    carried = carried[at:carried.index("**Not carried**", at)]
    step = next(ln for ln in (pr / "SKILL.md").read_text(encoding="utf-8").splitlines()
                if "Clean round:" in ln and "converge.py" in ln)
    for where, body in (("carried branch", carried), ("step 4", step)):
        assert "provision" in body and "check --expect --slug {slug}" in body, where
        assert "exit 1" in body and "no converge" in body, where
        assert body.index("check --expect") < body.index("converge.py"), where
