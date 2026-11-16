# Selection references

**Status (2026-11-16):** merged into `dnk-mcp-solidworks` 0.5.0 (tag
`datum-v0.2.0-selection` preserves the original branch history).

This note covers the selection/reference foundation that started as the
`datum/v02-selection` branch: reference tokens, topology enumeration, explicit
reference errors, and the `get_selection`, `resolve_entity_reference` and
`highlight_entities` tools. It is no longer a separate branch or an alternative
baseline; the behavior below is part of the released tool surface.

## Identity rules

Fingerprint matches must never win over persistent identity. After a captured
face changes, another face with its old fingerprint could otherwise win.
`resolve_entity_reference` checks persistent identity first and fails on multiple
persistent-id matches. Only lost persistent identity permits unique-fingerprint
fallback; missing and ambiguous fallback results fail explicitly.

Failure to read/compare a persistent identity is not proof of loss and fails
explicitly. Unreadable or incomplete geometry candidates also fail rather than
being discarded or treated as non-matches. This is intentionally conservative:
one incomplete topology candidate can make resolution unavailable. Tests
reproduce both wrong-face paths and confirm that fallback still succeeds when
comparisons complete and find no persistent match.

## Highlight ownership

Highlights are owner-scoped leases: `highlight_entities` requires an `owner`
token, appends only entities that are not already selected, and never reassigns
the engineer's marks. A clear removes only entries carrying this owner's mark and
captured identity, so a stale review cannot clear the engineer's selection.
Caller-owned tokens are single-use; clearing before applying fences a delayed
apply.

## Offset-face mutation

`resolve_offset_face` revalidates the captured planar face in the caller's CAD
job before an offset-plane mutation. Persistent identity alone is insufficient:
changed geometry requires re-selection, and no caller-supplied topology index is
accepted by that workflow.

## Edge fingerprints

Edge fingerprints sample the edge's trimmed span, not the untrimmed support
curve, so a truncated or trimmed edge cannot match a look-alike segment of its
parent curve. Vertex-less closed edges keep the `closed` signal when curve
parameters are unavailable.

## Verification

- `python -m pytest tests/unit -q` — pure token logic against a fake COM
  boundary. These do not claim new live SOLIDWORKS evidence.
- `python scripts/acceptance_selection.py` — live selection round-trip on a
  disposable part (survives save/reopen and rebuild).
- `python scripts/acceptance_datum_selection.py` — live identity, fail-closed and
  owned-highlight checks.
- `python scripts/acceptance_datum_capture.py` — `capture_screenshot` current-view
  acceptance.

Live scripts need an explicit disposable fixture and the engineer's saved-work
confirmation before attaching to SOLIDWORKS.
