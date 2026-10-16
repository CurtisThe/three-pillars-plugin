"""base_sync_plumbing.py -- pure parsers for git plumbing output, split out of
`base_sync_cert.py` (`skills/_shared/file-size-caps.md`: split by responsibility rather than grow a
file past its cap).

ONE responsibility: turn raw `git` plumbing stdout into structured values, or `None`. Nothing
here runs a subprocess, touches a repo, or knows anything about RME conditions -- that stays in
`base_sync_cert.py`. Every function is total and fail-closed: **any** shape anomaly returns
`None` rather than a guess, because the callers translate `None` into a refusal and a guess
there would be a silent mis-certification.

`base_sync_cert` re-imports these names into its own namespace, so existing references
(`base_sync_cert._parse_ls_tree_line`, `bsc._parse_merge_tree_z`, and monkeypatch seams in the
test suite) keep resolving unchanged.
"""
from __future__ import annotations

import re

_OID_RE = re.compile(r"^[0-9a-f]{40}$|^[0-9a-f]{64}$")
_MODE_RE = re.compile(r"^[0-7]{6}$")


def _redecode_strict_utf8(surrogate_str: str) -> str:
    """Re-derive true UTF-8 text from a seam string decoded with `errors="surrogateescape"`.
    Raises `UnicodeDecodeError` iff the original bytes were not valid UTF-8 -- the SAME
    strict-decode policy `auto_safe_resolution.decode_blob_strict` applies, expressed over the
    str-shaped seam channel instead of raw bytes."""
    return surrogate_str.encode("utf-8", "surrogateescape").decode("utf-8")


def _parse_merge_tree_z(out: str):
    """Parse `git merge-tree --write-tree -z --no-messages` stdout into `(tree_oid,
    conflicts)` where `conflicts` is `{path: {stage: (mode, oid)}}`. ANY shape anomaly --
    missing trailing NUL / trailing garbage, missing tree oid, malformed mode/oid, a
    non-integer or out-of-range (not 1-3) stage, a stanza missing its TAB-separated filename
    field, or an undecodable path -- returns None. The parser never guesses: an unrecognized
    shape is the caller's fail-closed "merge-tree output shape unrecognized"."""
    parts = out.split("\x00")
    if not parts or parts[-1] != "":
        return None
    parts = parts[:-1]
    if not parts:
        return None
    tree = parts[0]
    if not _OID_RE.match(tree):
        return None
    conflicts: dict = {}
    for stanza in parts[1:]:
        if "\t" not in stanza:
            return None
        head_part, path = stanza.split("\t", 1)
        fields = head_part.split(" ")
        if len(fields) != 3:
            return None
        mode, oid, stage_s = fields
        if not _MODE_RE.match(mode) or not _OID_RE.match(oid) or not stage_s.isdigit():
            return None
        stage = int(stage_s)
        if stage not in (1, 2, 3):
            return None
        try:
            path = _redecode_strict_utf8(path)
        except UnicodeDecodeError:
            return None
        conflicts.setdefault(path, {})[stage] = (mode, oid)
    return tree, conflicts


def _parse_dashz_names(out: str):
    """Parse a NUL-terminated `--name-only -z` path list. Empty stdout -> `[]`."""
    if out == "":
        return []
    if not out.endswith("\x00"):
        return None
    try:
        return [_redecode_strict_utf8(n) for n in out.split("\x00")[:-1]]
    except UnicodeDecodeError:
        return None


def _parse_ls_tree_line(out: str):
    line = out.rstrip("\n")
    if not line or "\t" not in line:
        return None
    head_part, _path = line.split("\t", 1)
    fields = head_part.split(" ")
    if len(fields) != 3:
        return None
    mode, _type, oid = fields
    if not _MODE_RE.match(mode) or not _OID_RE.match(oid):
        return None
    return mode, oid
