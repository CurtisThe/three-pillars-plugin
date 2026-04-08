# Name Validation

The `<design-name>` or `<spike-name>` argument must match `[a-z0-9-]+` only. Reject any value containing `/`, `..`, spaces, or characters outside `[a-z0-9-]`. This prevents path traversal — all TDD skills interpolate this value into file paths.
