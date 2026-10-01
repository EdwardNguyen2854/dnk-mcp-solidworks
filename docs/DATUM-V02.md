# Datum v0.2 selection branch

**Status (2026-10-02):** Isolated selection/reference foundation; not a release pin.

Branch `datum/v02-selection` starts from
`2254cfc4017f72c0101b7a78e4de187e488c487b` (0.4.0). It extracts only the
selection/reference work from the sibling development checkout: reference tokens,
topology enumeration, explicit reference errors, and `get_selection`,
`resolve_entity_reference`, `highlight_entities`. No drawing/image/modeling extensions
are included. The original development checkout is not modified.

## Identity correction

The extracted implementation tried fingerprint matches before persistent identity.
After a captured face changed, another face with its old fingerprint could win.
`resolve_entity_reference` now checks persistent identity first and fails on multiple
persistent-id matches. Only lost persistent identity permits unique-fingerprint fallback;
missing and ambiguous fallback results fail explicitly.

Public API regression tests use fake external COM objects. They do not claim new live
SOLIDWORKS evidence. Existing measured spike evidence remains in the original project
and Datum ADR-0011; this isolated extraction must be live-accepted separately.

## Open gates

- Owner-scoped highlight apply/clear and preservation of engineer-owned selection.
  Legacy `highlight_entities(clear=true)` clears all selection and is not safe cleanup
  for Datum review ownership.
- Reference-based planar-face mutation with same-call resolution and geometry eligibility.
- New revision/version, live acceptance, and Datum pin update. This branch is not an
  alternative already-supported production baseline.
- Edge fingerprint behavior must be live-verified against this extraction's baseline
  helpers; unrelated helper changes were not imported.

## Test from this source, not a global editable checkout

```powershell
python -c "import sys; sys.path.insert(0, 'src'); import pytest; raise SystemExit(pytest.main(['tests/unit', '-o', 'addopts=', '-q']))"
```

No live session is touched by these unit tests. Live scripts need an explicit disposable
fixture and the engineer's saved-work confirmation before attaching to SOLIDWORKS.
