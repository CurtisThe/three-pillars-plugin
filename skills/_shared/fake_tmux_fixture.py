"""fake_tmux_fixture.py — the in-memory tmux server the design_run_tmux tests drive.

design: design-run-launch-fixes (Task 1.7)

Not a test module (no `test_` prefix, never collected). FakeTmux holds session/window/link
state in dicts and records every call. A `-t` target it does not know (a stale `%pane` or
`@window`) answers like real tmux: no format output. tmux 3.4 exits 0 with an empty line
(display-message's target may fail); older tmux exits 1 with "can't find pane" — set
`stale_rc` to 1 for that shape.
"""
from __future__ import annotations


class FakeTmux:
    """Callable tmux stand-in: (rc, out) per call, state in dicts, calls recorded."""

    stale_rc = 0  # tmux 3.4: `display-message -p -t <gone>` exits 0 and prints nothing

    def __init__(self):
        self.sessions = {}   # session -> list of {id, index, dead, cmd[, name, path]}
        self.links = {}      # session -> set of linked-in window ids
        self.panes = {}      # pane id (`%N`) -> window id holding it
        self.calls, self.current, self._next = [], "seat", 0

    def sub(self, cmd):
        return [c for c in self.calls if c[0] == cmd]

    def __call__(self, args):
        args = list(args)
        self.calls.append(args)
        return getattr(self, "_" + args[0].replace("-", "_"))(args)

    def _arg(self, args, flag="-t"):
        return args[args.index(flag) + 1] if flag in args else None

    def _find(self, wid):
        hits = [(n, w) for n, ws in self.sessions.items() for w in ws if w["id"] == wid]
        return hits[0] if hits else (None, None)

    def _scan(self, name):  # a session's own windows plus linked-in copies
        wins = list(self.sessions.get(name, []))
        for wid in sorted(self.links.get(name, ())):
            _, w = self._find(wid)
            if w:
                wins.append(w)
        return wins

    def _fmt(self, wid, fmt):
        name, w = self._find(wid)
        return (fmt.replace("#{window_id}", wid).replace("#{session_name}", name)
                    .replace("#{window_name}", w.get("name", ""))
                    .replace("#{window_index}", str(w["index"]))) if w else ""

    def _pane(self, w, fmt):
        return (fmt.replace("#{pane_dead}", "1" if w["dead"] else "0")
                    .replace("#{window_id}", w["id"])
                    .replace("#{pane_current_path}", w.get("path", ""))
                    .replace("#{pane_pid}", "p" + w["id"]))

    def _stale(self, tgt):
        return (self.stale_rc, "" if self.stale_rc == 0 else f"can't find pane: {tgt}")

    def _has_session(self, args):
        name = self._arg(args).lstrip("=")
        return (0, "") if name in self.sessions else (1, f"can't find session {name}")

    def _new_session(self, args):
        self._next += 1
        wid = f"@{self._next}"
        self.sessions[args[args.index("-s") + 1]] = [{"id": wid, "index": 1, "dead": False,
                                                      "cmd": args[-1],
                                                      "name": self._arg(args, "-n") or ""}]
        return (0, self._fmt(wid, self._arg(args, "-F")))

    def _rows(self, args, render):
        tgt = self._arg(args)
        if "-a" in args:  # every session, a linked window once per session (as tmux lists it)
            wins = [w for name in list(self.sessions) for w in self._scan(name)]
        else:
            wins = [self._find(tgt)[1]] if tgt.startswith("@") else self._scan(tgt.lstrip("="))
        return (0, "\n".join(render(w) for w in wins if w))

    def _list_windows(self, args):
        return self._rows(args, lambda w: self._fmt(w["id"], self._arg(args, "-F")))

    def _list_panes(self, args):
        return self._rows(args, lambda w: self._pane(w, self._arg(args, "-F")))

    def _respawn_window(self, args):
        _, w = self._find(self._arg(args))
        w["dead"], w["cmd"] = False, args[-1]
        return (0, "")

    def _display_message(self, args):
        fmt, tgt = args[-1], self._arg(args)
        if tgt and tgt.startswith("%"):  # a pane: format its window, or a stale target
            tgt = self.panes.get(tgt) if self._find(self.panes.get(tgt))[1] else None
            if tgt is None:
                return self._stale(self._arg(args))
        if tgt and tgt.startswith("@"):
            return (0, self._fmt(tgt, fmt)) if self._find(tgt)[1] else self._stale(tgt)
        return (0, self.current) if "#{session_name}" in fmt else (1, "no target")

    def _set_option(self, args):  # window option: `-w -t <wid> <name> <value>`
        _, w = self._find(self._arg(args))
        if w is None:
            return self._stale(self._arg(args))
        w.setdefault("options", {})[args[-2]] = args[-1]
        return (0, "")

    def _rename_window(self, args):
        _, w = self._find(self._arg(args))
        if w is None:
            return self._stale(self._arg(args))
        w["name"] = args[-1]
        return (0, "")

    def _link_window(self, args):
        wid, dest = self._arg(args, "-s"), self._arg(args).rstrip(":").lstrip("=")
        if not self._find(wid)[1] or dest not in self.sessions:
            return (1, "can't find window or session")
        self.links.setdefault(dest, set()).add(wid)
        return (0, "")

    def _kill_window(self, args):
        name, w = self._find(self._arg(args))
        self.sessions[name].remove(w)
        for linked in self.links.values():
            linked.discard(w["id"])
        if not self.sessions[name]:
            del self.sessions[name]
        return (0, "")

    def _kill_session(self, args):
        name = self._arg(args).lstrip("=")
        if name not in self.sessions:
            return (1, f"can't find session {name}")
        ids = {w["id"] for w in self.sessions.pop(name)}
        self.links.pop(name, None)
        for linked in self.links.values():
            linked -= ids
        return (0, "")
