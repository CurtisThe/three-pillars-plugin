"""Shell layer for the reviewer-delete-guard: split a command into segments
and find each segment's real verb. Pure; raises Unmodelled for anything it
does not model so the classifier can fail closed."""
from __future__ import annotations

import os
import re
import shlex
from collections import namedtuple

from reviewer_delete_lex import Heredoc, Unmodelled, cut_heredocs  # noqa: F401

PUNCT = "();<>|&\n"
_PUNCT_OPS = "();<>|&"
SEMI = "__TP_P%d__" % ord(";")  # an escaped / quoted ';' (find's exec terminator)
Segment = namedtuple("Segment", "argv heredocs stdin")
Resolved = namedtuple("Resolved", "verb args stdin_fed chdir nested")

_OPS = sorted([">>", "&>>", "<<<", "<<", "&>", ">&", "<&", ">|", "<>", "|&", "&&", "||",
               ";;", ";", "|", "&", "(", ")", "<", ">", "\n"], key=len, reverse=True)
_SEPARATORS = {"\n", ";", ";;", "&&", "||", "|", "|&", "&", "(", ")"}
_REDIRECTS = {"<", ">", ">>", ">|", "<>", ">&", "<&", "&>", "&>>"}
_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\[[^]]*\])?\+?=")
KEYWORDS = {"{", "}", "!", "if", "then", "elif", "else", "do", "while", "until",
            "function", "coproc"}
_COMPOUND = {"{", "if", "while", "until", "for", "case", "select", "[["}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}


def _sentinels(chars):
    return " %s " % "".join("__TP_P%d__" % ord(c) for c in chars)


def _prep(text):
    """Turn escaped or whole-token quoted punctuation (find exec terminators)
    into sentinel words. Quote-aware: a close/open quote pair and an escaped
    backslash before an operator stay real separators."""
    text = re.sub(r"(?<![^\s;&|()])\d+(?=[<>])", "", text)  # fd numbers: 2>&1
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c == "\\":  # escapes exactly one char: `\\` is a literal backslash
            pair = text[i:i + 2]
            out.append(_sentinels(pair[1]) if pair[1:] and pair[1] in _PUNCT_OPS else pair)
            i += 2
        elif c in "'\"":
            j = i + 1
            while j < n and text[j] != c:
                j += 2 if c == '"' and text[j] == "\\" else 1
            if j >= n:  # unbalanced: shlex reports it
                out.append(text[i:])
                break
            body, edge = text[i + 1:j], (i == 0 or text[i - 1].isspace())
            if body and edge and all(ch in _PUNCT_OPS for ch in body) and (
                    j + 1 >= n or text[j + 1].isspace()):
                out.append(_sentinels(body))
            else:
                out.append(text[i:j + 1])
            i = j + 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _items(text):
    lex = shlex.shlex(text, posix=True, punctuation_chars=PUNCT)
    lex.whitespace_split, lex.whitespace, lex.commenters = True, " \t\r", ""
    try:
        toks = list(lex)
    except ValueError as exc:
        raise Unmodelled("unparseable: %s" % exc)
    items = []
    for tok in toks:
        if tok and all(c in PUNCT for c in tok):
            k = 0
            while k < len(tok):
                op = next((o for o in _OPS if tok.startswith(o, k)), None)
                if op is None:
                    raise Unmodelled("unparseable: punctuation %r" % tok)
                items.append(("op", op))
                k += len(op)
        else:
            items.append(("w", tok))
    return items


def parse(command):
    """Return (segments, scan_text); scan_text is what the shell would expand."""
    text, docs = cut_heredocs(command)
    scan = text + "".join("\n" + d.body for d in docs if not d.quoted)
    items, segs, docs = _items(_prep(text)), [], list(docs)
    argv, hds, stdin, i = [], [], None, 0

    def flush():
        nonlocal argv, hds, stdin
        if argv or hds or stdin is not None:
            segs.append(Segment(argv, hds, stdin))
        argv, hds, stdin = [], [], None

    while i < len(items):
        kind, val = items[i]
        i += 1
        if kind == "w":
            argv.append(val)
        elif val in _SEPARATORS:
            flush()
        elif val == "<<":
            if not docs:
                raise Unmodelled("unparseable: heredoc")
            hds.append(docs.pop(0))
            i += i < len(items) and items[i][0] == "w"
        elif val in _REDIRECTS or val == "<<<":
            if i < len(items) and items[i][0] == "w":
                if val == "<<<":
                    stdin = items[i][1]
                i += 1
        else:
            raise Unmodelled("unparseable: %r" % val)
    flush()
    return segs, scan


def segments(command):
    return parse(command)[0]


# name -> (options taking an argument, flag options, leading positionals)
def _w(arg="", flag="", pos=0):
    return (set(arg.split()), set(flag.split()), pos)


WRAPPERS = {
    "sudo": _w("u g C D h p r t T U R user group chdir host prompt role type close-from",
               "E H n S b k K v preserve-env non-interactive set-home stdin background"),
    "doas": _w("u C", "n s"),
    "env": _w("u C unset chdir", "i 0 v ignore-environment null debug"),
    "command": _w("", "v V p"), "builtin": _w(), "exec": _w("a", "c l"), "nohup": _w(),
    "time": _w("f o format output", "p a v portability append verbose"),
    "nice": _w("n adjustment"), "ionice": _w("c n p P u class classdata", "t ignore"),
    "stdbuf": _w("i o e input output error"),
    "timeout": _w("s k signal kill-after",
                  "f p v foreground preserve-status verbose", 1),
    "setsid": _w("", "c f w ctty fork wait"), "chrt": _w("", "b f i o r m R v", 1),
    "taskset": _w("c cpu-list", "a all-tasks", 1), "flock": _w("w E timeout conflict-exit-code",
                                                              "s x e n u o shared exclusive nonblock unlock", 1),
    "unbuffer": _w("", "p"), "busybox": _w(), "toybox": _w(),
    "xargs": _w("a d E I L n P s arg-file delimiter max-args max-procs max-lines max-chars",
                "0 r t p o x v null no-run-if-empty verbose open-tty exit"),
    "parallel": _w("j S a N n jobs sshlogin arg-file",
                   "0 k q X m r v t keep-order quote null"),
}


def _eat_options(name, spec, words, i, seen):
    arg, flag, _ = spec
    while i < len(words):
        w = words[i]
        if w == "--":
            return i + 1
        if w == "-" and name == "env":
            i += 1
        elif not w.startswith("-") or w == "-":
            return i
        elif w.startswith("--"):
            nm, eq, _v = w[2:].partition("=")
            if nm in arg:
                i += 1 if eq else 2
            elif nm in flag:
                i += 1
            else:
                raise Unmodelled("unparseable: %s option %s not modelled" % (name, w))
            seen.add(nm)
        else:
            k, step = 1, 1
            while k < len(w):
                ch = w[k]
                seen.add(ch)
                if ch in arg:
                    step = 1 if k + 1 < len(w) else 2
                    break
                if ch not in flag:
                    raise Unmodelled("unparseable: %s option %s not modelled" % (name, w))
                k += 1
            i += step
    return i


def _shell_nested(args, heredocs, stdin):
    k, c_seen = 0, False
    while k < len(args):
        a = args[k]
        if a == "--":
            k += 1
            break
        if a in ("-o", "+o", "-O", "+O", "--rcfile", "--init-file"):
            k += 2
        elif a.startswith("-") and not a.startswith("--") and len(a) > 1:
            c_seen = c_seen or "c" in a
            k += 1
        elif a.startswith("--") or a.startswith("+"):
            k += 1
        else:
            break
    if c_seen:
        return [args[k]] if k < len(args) else []
    if k < len(args) and "-s" not in args:
        return []  # a script file: not parsed (residual risk)
    nested = [h.body for h in heredocs] + ([stdin] if stdin is not None else [])
    if not nested:
        raise Unmodelled("unparseable: shell reads stdin")
    return nested


def resolve(argv, heredocs=(), stdin=None):
    words, i, n = list(argv), 0, len(argv)
    chdir = stdin_fed = False
    while True:
        while i < n and (words[i] in KEYWORDS or _ASSIGN.match(words[i])):
            # `function NAME` / `coproc NAME {`: NAME is a definition, not a verb
            named = words[i] == "function" or (words[i] == "coproc" and i + 2 < n
                                                and words[i + 2] in _COMPOUND)
            i += 2 if named else 1
        if i >= n:
            return Resolved(None, [], stdin_fed, chdir, [])
        name = os.path.basename(words[i])
        if name in ("type", "which"):
            return Resolved(None, [], stdin_fed, chdir, [])
        if name not in WRAPPERS:
            break
        seen = set()
        i = _eat_options(name, WRAPPERS[name], words, i + 1, seen)
        if name == "taskset" and seen & {"c", "cpu-list"}:
            pass
        else:
            i += WRAPPERS[name][2]
        chdir = chdir or bool(seen & {"C", "chdir", "D"}) and name in ("env", "sudo")
        stdin_fed = stdin_fed or name in ("xargs", "parallel")
        if name == "command" and seen & {"v", "V"}:
            return Resolved(None, [], stdin_fed, chdir, [])
    word, args = words[i], words[i + 1:]
    base = os.path.basename(word)
    if (any(ch in word for ch in "$`*?{}[") and word not in ("[", "[[")) or word.startswith("-"):
        raise Unmodelled("unparseable: verb %r" % word)
    if base in ("eval", "watch") or (base == "su" and any(
            a == "--command" or (a.startswith("-") and not a.startswith("--") and "c" in a)
            for a in args)):
        raise Unmodelled("unparseable: %s runs a string" % base)
    nested = _shell_nested(args, heredocs, stdin) if base in SHELLS else []
    return Resolved(base, args, stdin_fed, chdir, nested)
