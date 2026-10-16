# Test fragility: the rule every stage cites

Design, plan, implement, audit and review all cite this doc. A fragile test or check is the
main reason review loops run long: each "another input breaks it" finding invites a patch, and
each patch regresses something. Prevent the fragile form at the stage that writes it. The
wording is language-neutral; the examples are Python first.

## 1. The three kinds

**Open-ended check.** A regex or heuristic over free prose. Its input domain has no edge, so
there is always one more sentence that slips past it or trips it.

```python
# fragile: a heuristic over prose; every new phrasing is another finding
assert re.search(r"(should|must) not", doc_text)

# fix: have the system build the input, then assert on the structure it built
spec = build_spec(rule="no-writes")
assert spec.rules == ["no-writes"]
```

**Change-detector.** A pin on wording, a line number, a hash or the shape of the code. It fails
when the code is right and passes when it is wrong.

```python
# fragile: pins the exact text, so any rewording fails the test
assert render(task) == "Task 1.3: done (green)"

# fix: assert the behaviour a reader relies on, through a structured field
assert render_fields(task) == {"id": "1.3", "status": "green"}
```

**Blocklist.** A list of bad values that is never complete: there is always one more entry.

```python
# fragile: the next bad word needs a new entry, and a new finding
assert not any(word in text for word in ("foo", "bar", "baz"))

# fix: an allowlist derived from the system's own registry
assert set(used_names(text)) <= set(registry.NAMES)
```

## 2. The ordered fixes

Try them in this order and stop at the first that applies.

1. Delete a check whose measured value is zero. A check that has never caught a real defect
   costs every later round and buys nothing.
2. Have the system build the input, so the test never parses prose it did not make.
3. Use a structured field, validated when it is written, instead of reading free text later.
4. Use an allowlist derived from the system's own registry, never a hand-copied list.
5. Write a property or metamorphic test: state what holds for every input, or how the output
   moves when the input moves, instead of listing inputs.

Adding one more pattern, needle or list entry is not on this list. It is the failure mode.

## 3. Oracle types

The registry is `task_oracle.ORACLE_TYPES` in `skills/_shared/task_oracle.py`. This doc never
keeps a second copy of the list; the one-line glosses below follow the registry.

- `example`: one concrete input with its expected output, taken from the spec.
- `property`: a statement that holds for every generated input.
- `metamorphic`: a relation between the outputs of two related inputs.
- `schema`: the output validates against a declared structure.
- `round-trip`: encoding then decoding returns the original value.
- `differential`: two independent implementations agree on the same input.

The pairing rule: a `property` or `metamorphic` test has at least one `example` from the
spec. The example anchors the generated cases to what the spec actually says. A plan task
declares its types in its `**Oracle**` field, and `task_oracle` parses that grammar.

## 4. The input-domain question

Ask it of every check and every validator: is the input domain closed or open?

- Closed: an enum, a schema or a registry bounds the input. The check may enumerate it.
- Open: the input is prose or otherwise unbounded. The check needs a written justification for
  reading it, and an answer to "can the system construct this input itself?". If it can,
  build the input (fix 2) rather than parsing it.

## 5. Red from the spec

Write the red test from the design and plan text, never from the implementation. A test
derived from the code passes because the code says so, and pins whatever the code does today.
The task's Targets files are frozen after the red commit, once the rule ships: the green
commit edits the implementation, not the test it must satisfy.

## 6. What the tooling enforces

- `fragility_lint.py` scans Python tests and checks. The rule ids come from
  `fragility_registry.RULES`, which is the one list of rules.
- The per-repo rules file, `.three-pillars/fragility-rules.json`, adds a repo's own rules
  through the same closed rule kinds.
  A read through `skill_text.read_skill_text` or `skill_paths` counts as a `.md` read, and this
  repo gates new prose pins.
- `pred_fragility_clear` is the merge predicate. It covers only tests and checks a PR adds or
  changes, so an existing suite never blocks a first merge after upgrading.
- A deliberate exception carries an inline waiver, `# tp-allow-fragile: <reason>`. The reason
  is required: an empty reason does not silence the hit.

## 7. Review admissibility

- A finding needs a failing input and the spec clause it breaks. "Another input might break
  it" with no input is not a finding.
- A fragile test or check that the PR itself adds is a structural finding on its own. It needs
  no failing input.
- Mutation testing is diff-scoped and advisory. It is suppressed as a blocker: a surviving
  mutant is a note, not a reason to hold a merge.
- Only spec-derived tests are committed. A test written to pin a mutant or a coverage gap is
  not kept.

## 8. Other languages

The lint covers Python only. For every other language the same questions apply, and they are
a required judge dimension: which of the three kinds is this test, which fix applies, is the
input domain closed, and is the test derived from the spec. A judge that skips the dimension
has not reviewed the test.
