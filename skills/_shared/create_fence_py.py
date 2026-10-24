"""create_fence_py.py — the paths an inline Python body creates (design run-scratch-in-fence 1.4).

`python_targets(source)` returns `(literal_paths, unprovable)`. It walks call
sites with `delete_fence_py`'s source walker (import aliases, literal paths,
simple `name = Path(...)` bindings), never substrings, so a string holding
`open('/x', 'w')` is data, not a hit.

Read as creates: `open(p, mode)` with `w`, `a` or `x` in a literal mode (a
non-literal mode is unprovable, a missing or read mode is nothing),
`Path(p).write_text/write_bytes/mkdir/touch` and `Path(p).open(mode)`,
`os.makedirs(p)` and `os.mkdir(p)`, and the link maker `os.symlink(src, p)`
and `Path(p).symlink_to(src)` (`python_links` names those paths). A path that is
not a literal is unprovable. Paths are returned raw: the caller resolves a relative one. A
`SyntaxError` is unprovable. Stdlib only.
"""
from __future__ import annotations

import ast

from delete_fence_py import _aliases, _bound_names, _literal_path, _name, _receiver_path

_OPEN = {"open", "builtins.open", "io.open"}
_MAKEDIRS = {"os.makedirs", "os.mkdir"}
_SYMLINK = "os.symlink"
_PATH_CREATES = {"write_text", "write_bytes", "mkdir", "touch", "symlink_to"}
_CREATE_MODE = set("wax")


def _text(node):
    try:
        return ast.unparse(node)
    except Exception:  # noqa: BLE001 - only a label for the unprovable list
        return "<expr>"


def _mode(call, pos):
    """'create', 'read' or 'unknown' for an open-like call's mode argument."""
    node = call.args[pos] if len(call.args) > pos else next(
        (k.value for k in call.keywords if k.arg == "mode"), None)
    if node is None:
        return "read"
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return "create" if _CREATE_MODE & set(node.value) else "read"
    return "unknown"


def _site(call, aliases, names):
    """(kind, payload) for one call: ('path', text), ('unprovable', label) or None."""
    name = _name(call.func, aliases)
    if name in _OPEN:
        mode = _mode(call, 1)
        node = call.args[0] if call.args else next(
            (k.value for k in call.keywords if k.arg == "file"), None)
    elif name in _MAKEDIRS:
        mode = "create"
        node = call.args[0] if call.args else next(
            (k.value for k in call.keywords if k.arg in ("name", "path")), None)
    elif name == _SYMLINK:
        mode = "create"
        node = call.args[1] if len(call.args) > 1 else next(
            (k.value for k in call.keywords if k.arg == "dst"), None)
    elif isinstance(call.func, ast.Attribute) and (
            call.func.attr in _PATH_CREATES or call.func.attr == "open"):
        if call.func.attr == "open":
            mode = _mode(call, 0)
            if not _receiver_is_pathlike(call.func.value, aliases, names):
                return None
        else:
            mode = "create"
        text = _receiver_path(call.func.value, aliases, names)
        if mode == "read":
            return None
        if mode == "unknown" or text is None:
            return ("unprovable", _text(call))
        return ("path", text)
    else:
        return None
    if mode == "read":
        return None
    text = _literal_path(node, aliases) if node is not None else None
    if mode == "unknown" or text is None:
        return ("unprovable", _text(call))
    return ("path", text)


def _receiver_is_pathlike(node, aliases, names):
    """`.open()` counts only on a visible Path receiver (a file object's
    `.open` is not a create we can read)."""
    return _receiver_path(node, aliases, names) is not None


def _is_link(call, aliases):
    return _name(call.func, aliases) == _SYMLINK or (
        isinstance(call.func, ast.Attribute) and call.func.attr == "symlink_to")


def _collect(source):
    """[(hit, is_link)] for the creating calls of `source`, or None when unparseable."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    aliases = _aliases(tree)
    names = _bound_names(tree, aliases)
    sites = sorted((n for n in ast.walk(tree) if isinstance(n, ast.Call)),
                   key=lambda n: (n.lineno, n.col_offset))
    out = []
    for call in sites:
        hit = _site(call, aliases, names)
        if hit is not None:
            out.append((hit, _is_link(call, aliases)))
    return out


def python_targets(source):
    """(literal_paths, unprovable) for the creates in an inline Python body."""
    hits = _collect(source)
    if hits is None:
        return [], ["<unparseable python>"]
    paths, unprovable = [], []
    for hit, _link in hits:
        bucket = paths if hit[0] == "path" else unprovable
        if hit[1] not in bucket:
            bucket.append(hit[1])
    return paths, unprovable


def python_links(source):
    """The raw paths `source` makes as symlinks (a subset of `python_targets`' paths)."""
    return [hit[1] for hit, link in _collect(source) or [] if link and hit[0] == "path"]
