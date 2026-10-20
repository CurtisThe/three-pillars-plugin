"""`generator_catalog.py` as a CLI: `detect` / `accept` / `decline` against a real tmp repo.

The pure detector is covered in `test_generator_catalog.py`; this module covers the wiring - the
tracked paths from `git ls-files`, the config read from `.three-pillars/config.json`, and the ONE
`update_config` write that `accept` / `decline` make. Every assertion is observable from outside the
process: exit code, stdout, and the bytes of the config file.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

if shutil.which("git") is None:  # consumer-repo rule: skip cleanly, never fail, without git
    pytest.skip("git binary absent", allow_module_level=True)

SCRIPT = Path(__file__).resolve().parent / "generator_catalog.py"
SCHEMA = Path(__file__).resolve().parents[2] / "_shared" / "repo-config.schema.json"

EXISTING_GENERATOR = {"path": "gen/out.ts", "write": ["node", "gen.js"]}
CONFIG = {"schema_version": 1, "merge_from_main": {"generators": [EXISTING_GENERATOR]}}


def git(repo, *args) -> str:
    proc = subprocess.run(["git", "-C", str(repo)] + list(args),
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def run_cli(*args, cwd=None):
    return subprocess.run([sys.executable, str(SCRIPT)] + list(args),
                          capture_output=True, text=True, cwd=cwd)


def make_repo(tmp_path, config=CONFIG, tracked=("package.json", "package-lock.json")):
    """A tmp git repo with `tracked` in the index (no commit needed - `ls-files` reads the index)
    and `config` written to `.three-pillars/config.json`."""
    repo = tmp_path / "repo"
    for rel in tracked:
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
    git(repo, "init", "-q")
    git(repo, "add", "--", *tracked)
    if config is not None:
        cfg = repo / ".three-pillars" / "config.json"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return repo


def read_config(repo):
    return (repo / ".three-pillars" / "config.json").read_text(encoding="utf-8")


def test_detect_prints_items_and_writes_nothing(tmp_path):
    """`detect --json` reports the undeclared lockfile with its tool and entry, and leaves
    `config.json` byte for byte unchanged."""
    repo = make_repo(tmp_path)
    before = read_config(repo)
    proc = run_cli("detect", "--repo", str(repo), "--json", cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    items = json.loads(proc.stdout)
    assert [i["path"] for i in items] == ["package-lock.json"]
    assert items[0]["tool"] == "npm"
    assert items[0]["entry"] == {
        "path": "package-lock.json",
        "write": ["npm", "install", "--package-lock-only", "--ignore-scripts",
                  "--no-audit", "--no-fund"],
        "timeout": 300,
        "inputs": ["package.json"],
        "check": ["npm", "ci", "--dry-run", "--ignore-scripts", "--no-audit", "--no-fund"],
    }
    assert read_config(repo) == before


def test_detect_only_restricts_and_nested_lockfile_gets_cwd(tmp_path):
    """`--only` filters the report; a nested lockfile reports its directory, and the entry carries
    `cwd` with repo-relative `inputs`."""
    repo = make_repo(tmp_path, tracked=["apps/web/package.json", "apps/web/package-lock.json",
                                        "apps/api/pyproject.toml", "apps/api/uv.lock"])
    proc = run_cli("detect", "--repo", str(repo), "--only", "apps/api/uv.lock", "--json")
    assert proc.returncode == 0, proc.stderr
    items = json.loads(proc.stdout)
    assert [i["path"] for i in items] == ["apps/api/uv.lock"]  # --only filtered the other match
    assert items[0]["entry"]["cwd"] == "apps/api"
    assert items[0]["entry"]["inputs"] == ["apps/api/pyproject.toml"]


def test_accept_appends_entry_and_records_in_one_update(tmp_path):
    jsonschema = pytest.importorskip("jsonschema")
    repo = make_repo(tmp_path)
    proc = run_cli("accept", "--repo", str(repo), "--paths", "package-lock.json", cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(read_config(repo))
    assert data["schema_version"] == 1
    gens = data["merge_from_main"]["generators"]
    assert gens[0] == EXISTING_GENERATOR  # the old generator is kept, in order
    assert gens[1]["path"] == "package-lock.json"
    assert "--ignore-scripts" in gens[1]["write"]
    offer = data["merge_from_main"]["generator_offer"]
    assert offer["declined"] is False
    assert offer["offered_paths"] == ["package-lock.json"]
    assert isinstance(offer["offered_at"], str) and offer["offered_at"]
    jsonschema.validate(data, json.loads(SCHEMA.read_text(encoding="utf-8")))


def test_accept_of_an_unoffered_path_writes_only_the_offer(tmp_path):
    """Accepting a path the detector does not report still records it and adds no generator."""
    repo = make_repo(tmp_path)
    proc = run_cli("accept", "--repo", str(repo), "--paths", "gen/out.ts")
    assert proc.returncode == 0, proc.stderr
    data = json.loads(read_config(repo))
    assert [g["path"] for g in data["merge_from_main"]["generators"]] == ["gen/out.ts"]
    assert data["merge_from_main"]["generator_offer"]["offered_paths"] == ["gen/out.ts"]


def test_decline_records_and_suppresses_the_offer(tmp_path):
    """`decline` leaves the generators untouched, records `declined: true`, and a later `detect`
    returns nothing for those paths."""
    repo = make_repo(tmp_path)
    before = json.loads(read_config(repo))
    proc = run_cli("decline", "--repo", str(repo), "--paths", "package-lock.json", cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(read_config(repo))
    assert data["merge_from_main"]["generators"] == before["merge_from_main"]["generators"]
    assert data["merge_from_main"]["generator_offer"]["declined"] is True
    proc = run_cli("detect", "--repo", str(repo), "--json")
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == []


def test_lockfile_tracked_after_a_decline_is_offered(tmp_path):
    """A decline covers the paths it named, not the future: a lockfile tracked afterwards is
    reported by the next `detect`."""
    repo = make_repo(tmp_path, tracked=["package.json", "pyproject.toml", "uv.lock"])
    proc = run_cli("decline", "--repo", str(repo), "--paths", "uv.lock")
    assert proc.returncode == 0, proc.stderr
    (repo / "package-lock.json").write_text("{}\n", encoding="utf-8")
    git(repo, "add", "--", "package-lock.json")
    proc = run_cli("detect", "--repo", str(repo), "--json")
    assert proc.returncode == 0, proc.stderr
    assert [i["path"] for i in json.loads(proc.stdout)] == ["package-lock.json"]


def test_refused_write_exits_2_and_leaves_the_file_untouched(tmp_path):
    """A config `update_config` would have to prune is a refused write: exit 2, one stderr line,
    file byte-identical."""
    config = {"schema_version": 1,
              "merge_from_main": {"generators": [EXISTING_GENERATOR], "nonsense": 1}}
    repo = make_repo(tmp_path, config=config)
    before = read_config(repo)
    proc = run_cli("accept", "--repo", str(repo), "--paths", "package-lock.json")
    assert proc.returncode == 2
    assert proc.stderr.strip()
    assert read_config(repo) == before


def test_usage_errors_exit_2(tmp_path):
    repo = make_repo(tmp_path)
    assert run_cli("bogus").returncode == 2
    assert run_cli("accept", "--repo", str(repo)).returncode == 2  # --paths required
    assert run_cli().returncode == 2
