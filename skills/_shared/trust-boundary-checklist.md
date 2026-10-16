# Trust-boundary checklist

The repository under review has no SECURITY.md at its top level, so the security lens
works from this generic brief instead: for each trust-boundary surface the change touches,
what an attacker can control there, what to look for in the changed lines, and the shape of
a fix that counts. Nothing here is specific to one project; read the surface sections that
match the change and skip the rest.

## argv-subprocess

- **Attacker controls:** any value that reaches a command line: a file or branch name, a
  title, a message, a setting read from a repository or a remote response, text someone
  pasted in.
- **Check:** whether a command is assembled as one string and then handed to a shell;
  whether a variable is interpolated into it without quoting; whether this change removed
  a quoting or validation step that used to sit in front of it.
- **Fix:** pass the arguments as a list of separate values so nothing is re-parsed, or,
  when a shell is genuinely required, quote every interpolated value. An allowlist of
  permitted commands and flags beats any list of banned characters.

## file-write-path

- **Attacker controls:** a name or path that decides where something is written, moved or
  deleted: a filename from config, a path built from a title or an identifier, a name
  inside an archive or a downloaded document.
- **Check:** whether the destination is joined to a base directory and then confirmed to
  still be inside it; whether parent-directory traversal or a symlink can escape that base;
  whether a delete, move or cleanup step reaches outside the working area.
- **Fix:** build the destination from parts the code chose (a fixed base plus a name from
  an allowlist or a sanitised form), then resolve it and compare it to the base before
  writing. Reject what does not match instead of stripping the suspicious characters.

## credentials

- **Attacker controls:** anything able to see or carry a secret onward: logs, command lines
  other processes can read, error text, diffs, attachments, anything sent to a remote
  service.
- **Check:** whether a token, key, password or authorisation header ends up in a URL, a
  command argument, a printed environment value or a saved message; whether this change
  removed a redaction, a scope limit or a storage location that kept the secret out of
  view.
- **Fix:** hand the secret over through the environment or a permission-limited file, keep
  it out of arguments and printed output, and narrow it to the shortest scope and shortest
  lifetime that works. Narrowing the secret beats masking the print.

## git-gh

- **Attacker controls:** repository state and remote responses: branch and ref names,
  commit messages, hook files, configuration a clone brings with it, output from a remote
  command.
- **Check:** whether the change alters a command that pushes, resets, updates a ref or
  writes a hook; whether any hook or repository configuration file changed at all; whether
  a ref or branch name is interpolated into a command rather than passed as one argument.
- **Fix:** name the exact remote and the exact refspec, refuse the destructive forms, and
  treat hooks and configuration as code under review, with an explicit allowlist of what
  may run automatically.

## untrusted-parse

- **Attacker controls:** the document being parsed: structured data, a metadata block, a
  diff, a downloaded file, anything another program produced rather than this one.
- **Check:** whether the parser can execute or construct something on the way in (the
  unsafe load forms, evaluation of text, a pattern compiled from the input); whether the
  parsed result is treated as trustworthy afterwards, especially when it becomes a name, a
  path or a command.
- **Fix:** parse with the safest available loader against a schema that allowlists the keys
  and types expected, and treat every field that leaves the parse as unvalidated until it
  has been checked. Never evaluate input.

## agent-tool-grant

- **Attacker controls:** the text an automated assistant reads: file contents, web pages,
  issue bodies, tool output; anything that can carry instructions along with data.
- **Check:** whether the change widens which tools or commands are permitted, adds an allow
  entry, or removes an approval or permission step; whether a newly granted tool can reach
  the network, the filesystem or a credential.
- **Fix:** grant the narrowest set of named tools and paths, keep approval required for
  anything that writes or sends, and extend a deny-by-default set deliberately rather than
  opening a grant and narrowing it afterwards.

## The bar

A security finding blocks only with a demonstrated exploit path: the attacker-controlled input, the trust boundary it crosses and the effect, with a reproducer. Hardening ideas without one are notes (blocking=false). Prefer allowlist or build-the-input fixes; a blocklist patch is not a fix.
