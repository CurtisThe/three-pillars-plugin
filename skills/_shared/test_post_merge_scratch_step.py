"""Pin: /tp-post-merge step 4b runs the scratch leftover check (design: run-scratch-in-fence 1.8).

The doc step is read from SKILL.md; its command is run against a fake worktree under tmp_path.
"""
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import scratch_leftovers as sl  # noqa: E402

SKILL_MD = HERE.parent / "tp-post-merge" / "SKILL.md"
SLUG = "demo"
CMD_RE = re.compile(r'python3 "\$TP_ROOT"/skills/_shared/scratch_leftovers\.py (check [^`\n]*)')


def _text():
    return SKILL_MD.read_text(encoding="utf-8")


def _step_4b():
    t = _text()
    i = t.index("\n4b. ")
    return t[i:t.index("\n5. ", i)]


def test_step_4b_sits_between_merge_verify_and_teardown():
    t = _text()
    assert t.count("\n4b. ") == 1
    assert t.index("\n4. **Verify merge**") < t.index("\n4b. ") < t.index("\n5. **Teardown**")
    assert t.index("\n4b. ") < t.index("Unlanded-commit check")


def test_step_4b_text_pins():
    s = _step_4b()
    for word in ("--slug {name}", "--design-dir three-pillars-docs/completed-tp-designs/{name}",
                 "scratch-leftover:", "partial", "keep", "exit 1", "skipped", "baseline"):
        assert word in s, word
    assert "--reap" not in s and " reap " not in s


def test_step_7_lists_it():
    t = _text()
    assert "Scratch leftovers" in t[t.index("\n7. **Report**"):t.index("\n## Rules")]


def _section(start, end):
    t = _text()
    i = t.index(start)
    return t[i:t.index(end, i)]


def test_scan_form_runs_step_4b_and_5_for_each_selected_design():
    step = _section("\n4. Present an interactive checklist", "\n5. ")
    for word in ("steps 4b and 5", "each selected design", "4b exit 1", "keeps", "worktree",
                 "partial", "exit 1"):
        assert word in step, word


def test_auto_mode_teardown_bullet_runs_step_4b_too():
    bullet = _section("- **Verified-only teardown**", "\n- **No confirmation prompt**")
    for word in ("steps 4b and 5", "4b exit 1", "keeps", "partial"):
        assert word in bullet, word


def test_skill_stays_under_char_cap():
    assert len(_text()) < 35000


class Fx:
    def __init__(self, root, monkeypatch):
        self.root = root
        self.home, self.seat, self.wt = root / "home", root / "seat", root / "wt"
        self.areas = tuple(str(root / n) for n in ("tmp", "vartmp", "shm"))
        for d in (self.home, self.seat, *map(Path, self.areas)):
            Path(d).mkdir(parents=True)
        git = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run([*git, "init", "-q"], cwd=self.seat, check=True)
        subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "x"], cwd=self.seat, check=True)
        subprocess.run([*git, "worktree", "add", "-q", "-b", "tp/" + SLUG, str(self.wt)],
                       cwd=self.seat, check=True)
        self.env = {"HOME": str(self.home), "CLAUDE_CONFIG_DIR": str(self.home / ".claude")}
        monkeypatch.chdir(self.seat)

    def provision(self):
        argv = ["provision", "--slug", SLUG, "--worktree", str(self.wt)]
        assert sl.main(argv, env=self.env, areas=self.areas) == 0

    def doc_check(self):
        m = CMD_RE.search(_step_4b())
        assert m, "step 4b has no check command"
        argv = shlex.split(m.group(1).replace("{name}", SLUG))
        return sl.main(argv, env=self.env, areas=self.areas)


@pytest.fixture
def fx(tmp_path, monkeypatch):
    return Fx(tmp_path, monkeypatch)


def test_clean_tree_exits_zero(fx):
    fx.provision()
    assert fx.doc_check() == 0


def test_planted_leftover_exits_one_and_worktree_stays(fx, capsys):
    fx.provision()
    (fx.home / "stray-dir").mkdir()
    capsys.readouterr()
    assert fx.doc_check() == 1
    assert f"scratch-leftover: {fx.home / 'stray-dir'}" in capsys.readouterr().out
    assert fx.wt.is_dir()


def test_worktree_deleted_first_still_reports(fx, capsys):
    fx.provision()
    (fx.home / "stray-dir").mkdir()
    shutil.rmtree(fx.wt)
    capsys.readouterr()
    assert fx.doc_check() == 1
    assert f"scratch-leftover: {fx.home / 'stray-dir'}" in capsys.readouterr().out


def test_pre_design_skips_with_exit_zero(fx, capsys):
    capsys.readouterr()
    assert fx.doc_check() == 0
    assert "skipped" in capsys.readouterr().out
