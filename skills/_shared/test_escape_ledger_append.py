"""escape_ledger.append: one O_APPEND write per row, resolved dir, no interleave."""
from __future__ import annotations

import json
import threading

import escape_ledger


def _row(i=0):
    return escape_ledger.row("review_finder", "local", "d", "review", f"f{i}",
                             "kept", "local", "logic")


def _lines(path):
    return path.read_text(encoding="utf-8").splitlines()


def test_two_rows_two_lines(tmp_path):
    escape_ledger.append(tmp_path, [_row(1), _row(2)])
    lines = _lines(tmp_path / "escape-ledger.ndjson")
    assert [json.loads(x)["finding_id"] for x in lines] == ["f1", "f2"]


def test_archived_only_dir_resolves(tmp_path):
    slug = "my-design"
    archived = tmp_path / "completed-tp-designs" / slug
    archived.mkdir(parents=True)
    live = tmp_path / "tp-designs" / slug
    escape_ledger.append(live, [_row()])
    assert (archived / "escape-ledger.ndjson").is_file()
    assert not live.exists()


def test_concurrent_appends_do_not_interleave(tmp_path):
    def work(t):
        for i in range(25):
            escape_ledger.append(tmp_path, [_row(t * 100 + i)])

    threads = [threading.Thread(target=work, args=(t,)) for t in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    lines = _lines(tmp_path / "escape-ledger.ndjson")
    assert len(lines) == 100
    for line in lines:
        json.loads(line)
