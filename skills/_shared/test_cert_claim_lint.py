"""Tests for cert_claim_lint and its two CLI surfaces: `lint` and `fold --kept`.

design: certifier-lean (Task 1.1; Behaviors 1 and 4). A claim `certify.prepare` would
refuse is reported as one `<id>: <reason>` line and dropped before any certifier runs;
on `--light` only a changed production subject survives, at most `LIGHT_CAP`; a fold told
the kept ids never folds a dropped id `no-result`. The fixtures are real temp repos on
the repo's own git env (dev-repo only), so this file is tiered dev.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import certify
import certify_cli
from cert_claim_lint import LIGHT_CAP, is_production, lint
from test_cert_fold import _validate, envelope, result

# dev-only fixture modules, guarded so a tree that ships without them skips.
test_certify_scratch = pytest.importorskip("test_certify_scratch")
test_certify_status = pytest.importorskip("test_certify_status")
make_repo = test_certify_scratch.make_repo
FILES = test_certify_status.FILES
GUARD = test_certify_status.GUARD
claim = test_certify_status.claim
record = test_certify_status.record

NAME = "records/impl-audit.claims.json"
EXTRA = {**FILES, "test_util.py": "x = 1\n"}


def doc(*claims) -> dict:
    return {"disposition": "verdict", "claims": list(claims)}


def clean(*ids) -> list[dict]:
    return [claim(id=cid) for cid in ids]


def write_json(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def gclaims(*ids) -> list[dict]:
    return [{"id": i, "guard": GUARD, "property": "p", "parameters": []} for i in ids]


def ids(kept: dict) -> list[str]:
    return [c["id"] for c in kept["claims"]]


@pytest.fixture
def repo(tmp_path):
    return make_repo(tmp_path / "caller", EXTRA)


@pytest.fixture
def scratch(tmp_path):
    path = tmp_path / "scratch"
    path.mkdir()
    return path


def cli(*argv) -> int:
    return certify_cli.main([str(a) for a in argv])


# --- lint: the whole claims doc --------------------------------------------------------------

def test_clean_claim_passes(repo):
    path, sha = repo
    input_doc = doc(claim())
    out = lint(input_doc, NAME, repo=path, sha=sha)
    assert out["ok"] is True and out["lines"] == [] and out["dropped"] == []
    assert out["kept"] == input_doc


def test_claim_shape_reasons(repo):
    path, sha = repo
    cases = [
        (claim(guard="../x.py"), "c1: invalid:guard"),
        (claim(subjects=[GUARD, "docs/install.md"]), "c1: guard-is-subject"),
        (claim(extra="junk"), "c1: invalid:claim-extra-key"),
    ]
    for bad, expected in cases:
        out = lint(doc(bad), NAME, repo=path, sha=sha)
        assert out["ok"] is False and out["lines"] == [expected], expected
        assert out["dropped"] == [bad]
        assert out["kept"]["claims"] == []


def test_no_subjects_is_a_lint_line(repo):
    path, sha = repo
    bare = claim()
    del bare["subjects"]
    out = lint(doc(bare), NAME, repo=path, sha=sha)
    assert out["lines"] == ["c1: no-subjects"]
    assert out["dropped"] == [bare] and out["kept"]["claims"] == []


def test_resolution_at_the_ref(repo):
    path, sha = repo
    for over, expected in (
        ({"guard": "missing.py"}, "c1: guard-absent"),
        ({"guard": "docs"}, "c1: guard-not-file"),
        ({"subjects": ["docs/nope.md"]}, "c1: subject-absent:docs/nope.md"),
    ):
        out = lint(doc(claim(**over)), NAME, repo=path, sha=sha)
        assert out["lines"] == [expected], expected
        assert out["ok"] is False


def test_lint_agrees_with_prepare(repo):
    """Differential: every reason lint reports for a claim, prepare reports too."""
    path, sha = repo
    assert lint(doc(claim()), NAME, repo=path, sha=sha)["lines"] == []
    assert certify.prepare(claim(), record(), repo=path, sha=sha)[2] == []
    for over in ({"guard": "missing.py"}, {"guard": "docs"}, {"guard": "../x.py"},
                 {"subjects": ["docs/nope.md"]}, {"subjects": [GUARD, "docs/install.md"]},
                 {"extra": "junk"}):
        reported = [line.partition(": ")[2] for line in
                    lint(doc(claim(**over)), NAME, repo=path, sha=sha)["lines"]]
        prepared = certify.prepare(claim(**over), record(**over), repo=path, sha=sha)[2]
        assert reported and set(reported) <= set(prepared), over


def test_file_level_reason_drops_every_claim(repo):
    path, sha = repo
    wrong = {"disposition": "ledger", "claims": clean("c1", "c2")}
    out = lint(wrong, "impl-audit.claims.json", repo=path, sha=sha)
    assert out["lines"] == ["file: disposition-name"]
    assert out["ok"] is False
    assert out["dropped"] == wrong["claims"]
    assert out["kept"]["claims"] == []


def test_doc_cap_is_a_file_level_line(repo):
    path, sha = repo
    many = clean(*[f"c{i}" for i in range(1, 28)])
    out = lint(doc(*many), NAME, repo=path, sha=sha)
    assert out["lines"] == ["file: cap"] and out["kept"]["claims"] == []


# --- the light rules (Behavior 4) ------------------------------------------------------------

def test_light_cap_keeps_the_first_six(repo):
    path, sha = repo
    eight = clean(*[f"c{i}" for i in range(1, 9)])
    out = lint(doc(*eight), NAME, repo=path, sha=sha, light=True,
               diff_paths=["docs/install.md"])
    assert ids(out["kept"]) == [f"c{i}" for i in range(1, LIGHT_CAP + 1)]
    assert out["lines"] == ["c7: light:over-cap", "c8: light:over-cap"]
    assert out["ok"] is False
    assert out["dropped"] == eight[LIGHT_CAP:]


def test_light_subject_must_be_a_changed_production_file(repo):
    path, sha = repo
    claims = [claim(), claim(id="c2", subjects=["docs/install.md"]),
              claim(id="c3", subjects=["test_util.py"])]
    out = lint(doc(*claims), NAME, repo=path, sha=sha, light=True,
               diff_paths=["docs/old.md"])
    assert out["lines"] == ["c2: light:subject-not-in-diff", "c3: light:subject-not-in-diff"]
    assert ids(out["kept"]) == ["c1"]

    moved = lint(doc(claims[2]), NAME, repo=path, sha=sha, light=True,
                 diff_paths=["test_util.py"])
    assert moved["lines"] == ["c3: light:subject-not-in-diff"]
    assert moved["kept"]["claims"] == []


def test_light_cap_counts_only_passing_claims(repo):
    path, sha = repo
    seven = [claim(id="c1"), claim(id="c2", guard="missing.py")]
    seven += clean(*[f"c{i}" for i in range(3, 8)])
    out = lint(doc(*seven), NAME, repo=path, sha=sha, light=True,
               diff_paths=["docs/install.md"])
    assert ids(out["kept"]) == ["c1", "c3", "c4", "c5", "c6", "c7"]
    assert not [line for line in out["lines"] if "light:over-cap" in line]


def test_light_without_diff_paths_is_a_value_error(repo):
    path, sha = repo
    with pytest.raises(ValueError):
        lint(doc(claim()), NAME, repo=path, sha=sha, light=True)


def test_full_mode_has_no_light_rules(repo):
    """Behavior 4: a full design's count and selection are unchanged."""
    path, sha = repo
    eight = clean(*[f"c{i}" for i in range(1, 9)])
    out = lint(doc(*eight), NAME, repo=path, sha=sha, light=False, diff_paths=None)
    assert out["ok"] is True and ids(out["kept"]) == [f"c{i}" for i in range(1, 9)]
    assert out["lines"] == [] and out["dropped"] == []


def test_is_production_skips_tests_and_docs():
    assert is_production("app/handler.py") and is_production("docs/install.md")
    assert not is_production("conftest.py")
    assert not is_production("skills/_shared/test_x.py")
    assert not is_production("scripts/run_test.py")
    assert not is_production("three-pillars-docs/tp-designs/x/design.md")


# --- the lint subcommand ---------------------------------------------------------------------

def test_cli_kept_doc_equals_the_input_when_nothing_is_dropped(repo, scratch, capsys):
    path, _sha = repo
    claims = write_json(scratch / NAME, doc(claim()))
    kept = scratch / "kept.json"
    code = cli("lint", "--claims", claims, "--ref", "HEAD", "--repo", path,
               "--kept-out", kept)
    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True and report["lines"] == [] and report["dropped"] == []
    assert json.loads(kept.read_text(encoding="utf-8")) == doc(claim())


def test_cli_failing_doc_exits_1_and_keeps_the_passing_subset(repo, scratch, capsys):
    path, _sha = repo
    claims = write_json(scratch / NAME, doc(claim(), claim(id="c2", guard="missing.py")))
    kept = scratch / "kept.json"
    code = cli("lint", "--claims", claims, "--ref", "HEAD", "--repo", path,
               "--kept-out", kept)
    assert code == 1
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is False and report["lines"] == ["c2: guard-absent"]
    assert report["dropped"] == [claim(id="c2", guard="missing.py")]
    assert json.loads(kept.read_text(encoding="utf-8")) == doc(claim())


def test_cli_light_rules_apply_with_a_diff_file(repo, scratch):
    path, _sha = repo
    claims = write_json(scratch / NAME, doc(claim(), claim(id="c2", subjects=["docs/old.md"])))
    diff = scratch / "diff.txt"
    diff.write_text("docs/install.md\n", encoding="utf-8")
    kept = scratch / "kept.json"
    code = cli("lint", "--claims", claims, "--ref", "HEAD", "--repo", path,
               "--light", "--diff", diff, "--kept-out", kept)
    assert code == 1
    assert json.loads(kept.read_text(encoding="utf-8")) == doc(claim())


def test_cli_bad_input_is_exit_2(repo, scratch):
    path, _sha = repo
    claims = write_json(scratch / NAME, doc(claim()))
    assert cli("lint", "--claims", claims, "--ref", "HEAD", "--repo", path,
               "--light") == 2, "--light without --diff"
    assert cli("lint", "--claims", scratch / "absent.claims.json", "--ref", "HEAD",
               "--repo", path) == 2, "unreadable --claims"
    assert cli("lint", "--claims", claims, "--ref", "HEAD", "--repo", path,
               "--diff", scratch / "absent.txt") == 2, "unreadable --diff"


# --- fold --kept ------------------------------------------------------------------------------

def fold_cli(scratch, env, results, kept=None) -> tuple[int, dict | None]:
    argv = ["fold", "--envelope", write_json(scratch / "env.json", env),
            "--result", write_json(scratch / "r.json", results[0]),
            "--slot", "8", "--out", scratch / "out.json"]
    if kept is not None:
        argv += ["--kept", kept]
    code = cli(*argv)
    out = scratch / "out.json"
    return code, (json.loads(out.read_text(encoding="utf-8")) if out.exists() else None)


def test_fold_kept_skips_dropped_ids(scratch):
    env = envelope("pass", guard_claims=gclaims("c1", "c2"))
    covered = result(("c1", "binds"), name=NAME)
    kept_doc = write_json(scratch / "kept.json", doc(claim()))

    code, out = fold_cli(scratch, env, [covered], kept=kept_doc)
    assert code == 0
    assert out["verdict"] == "pass" and out["certifications"]
    assert [c for c in out["certifications"] if c["file"] == "guard_claims"] == []
    _validate(out)

    code, out = fold_cli(scratch, env, [covered])
    assert code == 0
    missing = [c for c in out["certifications"] if c["file"] == "guard_claims"]
    assert [(c["id"], c["status"], c["reasons"]) for c in missing] == [
        ("c2", "unverified", ["no-result"])]
    assert out["verdict"] == "unverified"


def test_fold_kept_naming_an_unreadable_file_is_exit_2(scratch):
    env = envelope("pass", guard_claims=gclaims("c1"))
    code, out = fold_cli(scratch, env, [result(("c1", "binds"), name=NAME)],
                         kept=scratch / "absent.json")
    assert (code, out) == (2, None)
