"""Lexical pre-pass for the reviewer-delete-guard shell layer: cut heredoc
bodies out, drop `#` comments and splice backslash-newline continuations.

One left-to-right scanner owns quote state ('...', "...", $'...'), backslash
escapes and expansion nesting (`$(..)`, `$((..))`, `${..}`, `<(..)`, `>(..)`
and backquotes), so a `#`, a `<<` or a trailing backslash is judged by what
bash would see, never by peeking at the raw previous character:

- a backslash escapes exactly the next char outside single quotes, so an even
  run of backslashes escapes nothing and a line ending in one is not continued;
- `#` starts a comment only when unquoted, unescaped, outside every expansion
  and at a word start (start of input, or after unquoted unescaped whitespace
  or `;&|()<>`); the `)`, `}` or backquote that closes an expansion is not a
  word break, so `$(x)#` and `${x}#` stay one word;
- inside an expansion a `#` at a word start, a `case` (whose `)` patterns do
  not close it), a stray closer or a missing closer is not modelled;
- a quoted heredoc body (`<<'EOF'`) gets no continuation processing.

Anything left ambiguous raises Unmodelled (fail closed). Pure; stdlib only."""
from __future__ import annotations

import re
from collections import namedtuple

Heredoc = namedtuple("Heredoc", "body quoted")
_HD = re.compile(r"<<(-?)[ \t]*((?:\\.|'[^']*'|\"[^\"]*\"|[^\s;&|()<>'\"\\])+)")
_WORD_BREAK = " \t\n;&|()<>"
_OPEN = re.compile(r"\$\(|\$\{|<\(|>\(")  # `$((` is `$(` then `(`
_CLOSER = {"(": ")", "{": "}"}
_CASE = re.compile(r"case[ \t\n]")


class Unmodelled(Exception):
    """A construct the shell layer does not model (the classifier refuses it)."""


def _odd_tail(line):
    """True when `line` ends in an odd run of backslashes (a continuation)."""
    return (len(line) - len(line.rstrip("\\"))) % 2 == 1


def _body_line(lines, i, quoted):
    """One logical heredoc body line from physical line `i`. An unquoted body
    splices backslash-newline continuations (bash pairs `\\\\`, so only an odd
    tail continues); a quoted body takes each physical line verbatim."""
    line, i = lines[i], i + 1
    while not quoted and _odd_tail(line) and i < len(lines):
        line = line[:-1] + lines[i]
        i += 1
    return line, i


def _read_bodies(text, pos, pending, docs):
    """Read each pending heredoc body starting at offset `pos` (just past the
    newline that ends the command line). Returns the offset after the last
    delimiter line. An unterminated body would swallow every later line, so it
    is refused."""
    lines, i = text[pos:].split("\n"), 0
    for dash, delim, quoted in pending:
        body = []
        while True:
            if i >= len(lines):
                raise Unmodelled("unparseable: heredoc %r has no terminator" % delim)
            ln, i = _body_line(lines, i, quoted)
            ln = ln.lstrip("\t") if dash else ln
            if ln == delim:
                break
            body.append(ln)
        docs.append(Heredoc("".join(b + "\n" for b in body), quoted))
    consumed = sum(len(ln) + 1 for ln in lines[:i])
    return min(len(text), pos + consumed)


def _heredoc_word(text, j, pending, out):
    """Record the `<<WORD` at `j` in `pending`; returns the offset past it."""
    m = _HD.match(text, j)
    if not m:
        out.append("<<")
        return j + 2
    word = m.group(2)
    if any(ch in word for ch in "$`"):
        raise Unmodelled("unparseable: heredoc delimiter %r" % word)
    pending.append((m.group(1) == "-", re.sub(r"[\\'\"]", "", word),
                    any(ch in word for ch in "'\"\\")))
    out.append("<< __TP_HD__ ")
    return m.end()


def _backquote(text, j, pending, out):
    """Copy the backquoted substitution at `j` verbatim; returns the offset
    past its closing backquote. bash finds that closer before it parses the
    inside (only a backslash escapes it; quotes do not hide it), so a `#` at a
    word start inside, a newline ahead of a pending heredoc body or a missing
    closer is not modelled."""
    k, n, word_start = j + 1, len(text), True
    while k < n and text[k] != "`":
        c = text[k]
        if c == "\\":
            k, word_start = k + 2, False
            continue
        if c == "#" and word_start:
            raise Unmodelled("unparseable: # inside backquotes")
        if c == "\n" and pending:
            raise Unmodelled("unparseable: newline in backquotes before a heredoc body")
        word_start, k = c in _WORD_BREAK, k + 1
    if k >= n:
        raise Unmodelled("unparseable: backquote has no closer")
    out.append(text[j:k + 1])
    return k + 1


def cut_heredocs(text):
    """Return (text without heredoc bodies, comments or continuations, docs)."""
    out, docs, pending, stack = [], [], [], []  # stack: (closer, quote to restore)
    quote, word_start, j, n = None, True, 0, len(text)
    while j < n:
        c = text[j]
        if quote == "'":
            out.append(c)
            quote = None if c == "'" else quote
            j += 1
            continue
        if c == "\\":
            nxt = text[j + 1:j + 2]
            if nxt == "\n" and quote != "$'":
                j += 2  # line continuation: bash removes both, word state holds
                continue
            if quote == "$'" and nxt == "'":
                raise Unmodelled("unparseable: escaped quote in $'...'")
            out.append(text[j:j + 2])
            word_start, j = False, j + 2
            continue
        if c == "`" and quote != "$'":
            j, word_start = _backquote(text, j, pending, out), False
            continue
        opener = None if quote == "$'" else _OPEN.match(text, j)
        if opener and (quote is None or opener.group()[0] == "$"):
            stack.append((_CLOSER[opener.group()[1]], quote))  # "..." resumes at the closer
            out.append(opener.group())
            quote, word_start, j = None, opener.group()[1] == "(", opener.end()
            continue
        if quote:  # '"' or "$'"
            if c == "\n" and pending:
                raise Unmodelled("unparseable: quoted newline before a heredoc body")
            out.append(c)
            quote = None if c == quote[-1] else quote
            j += 1
            continue
        if stack and c in ")}":
            closer, restore = stack.pop()
            if c != closer:
                raise Unmodelled("unparseable: %r inside an expansion closed by %r" % (c, closer))
            out.append(c)
            quote, word_start, j = restore, False, j + 1
            continue
        if stack and word_start and (c == "#" or _CASE.match(text, j)):
            raise Unmodelled("unparseable: %s inside an expansion" % ("#" if c == "#" else "case"))
        if c == "#" and word_start:
            while j < n and text[j] != "\n":
                j += 1  # the comment runs to the newline; the newline stays
            continue
        if c == "\n" and pending:
            if stack:  # bash reads the body only after the line closing the expansion
                raise Unmodelled("unparseable: newline in an open expansion before a heredoc body")
            out.append(c)
            j = _read_bodies(text, j + 1, pending, docs)
            pending, word_start = [], True
            continue
        if text.startswith("$'", j):
            out.append("$'")
            quote, word_start, j = "$'", False, j + 2
            continue
        if c in "'\"":
            quote = c
        elif stack and c in "({":
            stack.append((_CLOSER[c], None))
        elif text.startswith("<<<", j):
            out.append("<<<")
            word_start, j = True, j + 3
            continue
        elif text.startswith("<<", j):
            j, word_start = _heredoc_word(text, j, pending, out), True
            continue
        out.append(c)
        word_start = c in _WORD_BREAK
        j += 1
    if stack:
        raise Unmodelled("unparseable: expansion has no closer")
    if pending:
        raise Unmodelled("unparseable: heredoc with no body")
    return "".join(out), docs
