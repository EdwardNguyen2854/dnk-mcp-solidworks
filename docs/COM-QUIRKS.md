# SOLIDWORKS COM quirks log

Everything here was observed on this machine (SOLIDWORKS 2026 SP0.0, typelib
34.0, Python 3.12, pywin32 309) unless attributed otherwise. Each entry names
the mitigation in this codebase.

## Binding / dispatch

- `EnsureModule(LIBID, 0, 0, 0)` fails with `Library not registered`; only the
  exact registered major version works. Mitigation: probe majors 40..20 in
  `com/binding.py`.
- `ISldWorks.NewDocument` and `ISldWorks.ActiveDoc` return untyped `CDispatch`
  even from early-bound objects; calling `FirstFeature` on them raises
  `DISP_E_MEMBERNOTFOUND`. Mitigation: `binding.wrap(obj, "IModelDoc2")`.
- Members declared `PROPGET` with arguments surface as bound methods on plain
  attribute access (`app.RevisionNumber`). Mitigation: `binding.value()`.
- The generated makepy module is ~6 MB of Python; first attach pays the
  generation cost once (cached in `%TEMP%\gen_py`).

## Units

- The COM API is metres/radians; tool parameters are `_mm`/`_deg` and are
  converted exactly once, in `com/units.py`.
- `IPartDoc.GetPartBox(False)` returns document units, not metres
  (documented by Slacker-LLC); always pass `True`.

## Modal dialogs

- This install has `Input Value On Dimension Creation = 1` (HKLM General).
  `AddDimension2` therefore pops the modal "Modify" dialog, which blocks the
  COM call that opened it and deadlocks the server until dismissed.
  Mitigation: dimension tools toggle the preference off and restore it, and a
  modal-state preflight runs before dimension operations.
- Unknown modal dialogs must be inspected by a human; the server never
  auto-confirms them.

## Return values

- `FeatureExtrusion3` takes **23 arguments** in this typelib (the published
  reference documents 7). Signatures in this server are taken from the
  typelib via `scripts/probe_api.py`.
- Many `Create*`/feature calls return `None` or `VARIANT` arrays whose
  truthiness is unreliable; success is judged by rebuild + `GetWhatsWrong` +
  measured mass properties, never by the return value alone.
- `sketch_trim` returns `False` on success (documented by Slacker-LLC).

## Selection

- `SelectByID2` consumes 9 arguments including `Mark` and `SelectOption`;
  marks matter per feature (`InsertRefPlane` reads refs from marks 0/1/2).
- Snapshot indices from topology listings are invalidated by any geometry
  change; the API contract requires re-listing.

## Environment

- Default templates exist at
  `C:\ProgramData\SOLIDWORKS\SOLIDWORKS 2026\templates` (`Part.PRTDOT`,
  `Assembly.ASMDOT`, `Drawing.DRWDOT`).
- `API SAFETY CHECKS ENABLED = 1` in HKCU General on this install.
- `Show Feature Names in Translated Language = 0`; the UI language setting is
  `Use English language = 0`. Never match on display names where an API token
  exists; plane selection falls back to enumerating `RefPlane` features.
