# Releasing tuck-it

tuck-it is licensed under the **Business Source License 1.1** (see [`LICENSE`](../LICENSE)).
We use a **rolling Change Date**: every release resets the license's `Change Date`
to four years after that release. This keeps each version under BSL for its full
four-year window before it converts to Apache 2.0.

## Why rolling (and why it's BSL-compliant)

BSL 1.1 is designed for exactly this. Two clauses make it explicit:

- The Terms state a version converts on the `Change Date` **or the fourth
  anniversary of that version's first public distribution, whichever comes
  first.** So the effective conversion is always capped at 4 years — setting the
  `Change Date` to *release + 4 years* is the maximum the license allows.
- The Terms also state: *"This License applies separately for each version of the
  Licensed Work and the Change Date may vary for each version."* Updating the
  `Change Date` parameter per release is a supported use of the parameter, **not**
  a prohibited modification of the license (Covenant 4).

If we instead left the `Change Date` fixed, every version released *after* that
date would convert to Apache 2.0 the moment it ships (Change Date already in the
past → protection window of zero). Rolling avoids that.

## Release checklist

For every tagged release:

1. **Bump the version** (tag / changelog as applicable).
2. **Update the BSL `Change Date`** in [`LICENSE`](../LICENSE):
   - Set it to **the release date + 4 years** (the maximum BSL permits).
   - Example: releasing on `2027-03-15` → `Change Date: 2031-03-14`.
   - Leave `Change License: Apache License, Version 2.0` and the
     `Additional Use Grant` unchanged unless the licensing strategy itself is
     being revised.
3. **Confirm README matches LICENSE** — the license summary in
   [`README.md`](../README.md) must stay consistent with `LICENSE`
   (license name, the "not open source / source-available" framing, and the
   Change License). Do not restate the exact Change Date in the README so it does
   not drift; point to `LICENSE` for the authoritative date.
4. **Tag and publish.**

## Notes

- The `Additional Use Grant` (self-hosting and production use allowed; offering
  tuck-it as a third-party hosted/managed service is not) is the actual
  monetization boundary. Revisit it deliberately, not as part of routine
  releases.
- Each shipped version keeps whatever `Change Date` it was released with — older
  tags are not retroactively changed. Rolling only affects the *next* release.
