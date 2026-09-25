# SOLIDWORKS COM quirks log

Everything here was observed on this machine (SOLIDWORKS 2026 SP0.0, typelib
34.0, Python 3.12, pywin32 312) unless attributed otherwise. Each entry names
the mitigation in this codebase.

## Binding / dispatch

- `EnsureModule(LIBID, 0, 0, 0)` fails with `Library not registered`; only the
  exact registered major version works. Mitigation: probe majors 40..20 in
  `com/binding.py` (SW2026 = 34).
- `ISldWorks.NewDocument` and `ISldWorks.ActiveDoc` return untyped `CDispatch`
  even from early-bound objects; calling `FirstFeature` on them raises
  `DISP_E_MEMBERNOTFOUND`. Mitigation: `binding.wrap(obj, "IModelDoc2")`
  (QueryInterface the raw `PyIDispatch`, then construct the generated class).
- `IModelDoc2.SelectionManager` also returns an untyped dispatch;
  `CreateSelectData()` fails with `Member not found` until it is wrapped as
  `ISelectionMgr`.
- Members declared `PROPGET` with arguments surface as bound methods on plain
  attribute access (`app.RevisionNumber`). Mitigation: `binding.value()`.
- The generated makepy module is ~6 MB of Python; first attach pays the
  generation cost once (cached in `%TEMP%\gen_py`).

## Out parameters (load-bearing)

- makepy-generated methods with `[in,out]` parameters must be called with
  **plain values** (never `win32com.client.VARIANT`) and return the out
  values appended to the return value:
  `(ok, errors, warnings) = ext.SaveAs3(path, 0, 1, None, None, 0, 0)`.
  Passing VARIANT raises `TypeError: int() argument ... not 'VARIANT'`;
  omitting the arguments raises `Type mismatch`.
- `ISldWorks.CloseDoc(Name)` returns **void**; verify closure by re-reading
  `GetDocuments()`.
- `IModelDoc2.InsertFeatureShell` returns **void**; find the new feature by
  diffing feature names before/after.

## Units

- The COM API is metres/radians; tool parameters are `_mm`/`_deg` and are
  converted exactly once, in `com/units.py`.
- `IFace2.GetTessTriangles(False)` returns values in **document units** (mm
  here), while `NoConversion=True` returns system units (metres). Mixing them
  up produces selection points 1000x off, which silently selects nothing.
- `IPartDoc.GetPartBox(False)` returns document units (documented by
  Slacker-LLC); always pass `True`.
- `IPartDoc.GetBodies2(-1, True)` enumerates all bodies (`swAllBodies = -1`).

## Mass properties

- `CreateMassProperty()` initialises lazily. If `Volume` is read before
  `Density`, `Density` and `Mass` fall back to the default 1.0 even with a
  material assigned. Mitigation: `inspect.mass_properties` reads `Density`
  first.

## Selection

- The generated `IFace2` / `IEdge` / `ISketchSegment` classes expose **no**
  `Select*` members; the same COM object QueryInterfaced to `IEntity` does.
  Mitigation: `inspect.select_entity` wraps as `IEntity`, then tries
  `Select4(append, ISelectData)` (marks), `Select2(append, mark)`, `Select`.
- `ISelectionMgr.CreateSelectData()` gives an `ISelectData`; set `.Mark` on it
  for features that read references by mark.
- `SelectByID2("", "FACE", x, y, z, ...)` works when the coordinates are
  correct, but returns `False` (or picks nothing) when any coordinate is off;
  the entity path is preferred.
- `SelectByID2` consumes 9 arguments including `Mark` and `SelectOption`.
- `IEdge` has no `GetLength`; compute length from
  `edge.GetCurveParams()` (`params[6]`, `params[7]`) plus
  `ICurve.GetLength3(start_param, end_param)`.

## Modal dialogs

- This install has `Input Value On Dimension Creation = 1`; `AddDimension2`
  then opens a modal "Modify" dialog that blocks the COM call that opened it.
  During a long test run this crashed the session (RPC failure). Mitigation:
  dimension tools toggle `swUserPreferenceToggle_e.swInputDimValOnCreate`
  (10) off and restore it afterwards.
- A crash leaves a MyPDM add-in prompt (`#32770` dialog) blocking startup;
  clicking "No, disable MyPDM" lets SOLIDWORKS finish loading.
- Unknown modal dialogs must be inspected by a human; the server never
  auto-confirms them.

## Typed arrays (marshalling)

- SOLIDWORKS methods that take double arrays must receive
  `VT_ARRAY|VT_R8` VARIANTs. A bare Python list is marshalled as an array of
  variants and silently misread: `CreateVector([1, 2, 3])` comes back as
  `(garbage, 1.0, 0.0)` and `CreateTransform` ignores most of the input.
  Mitigation: `binding.r8_array()`.
- `IMathTransform` has two disagreeing array layouts: the `CreateTransform`
  input layout is not the same as the `ArrayData` output layout. Use
  `CreateTransform(identity)` then `SetData(x_axis, y_axis, z_axis,
  translation, scale)`; axes are the rotation matrix **rows** (verify with a
  90-degree rotation). `ArrayData` returns rotation in 0..8 (row-major),
  translation in 9..11, scale in 12.
- `ArrayData` PROPPUT and `CreateTransform` with a full matrix are both
  unreliable on this build; only getter + `SetData` round-trip correctly.

## Assemblies

- `AddComponent5` (and `AddComponent`/`AddComponent2`/`AddComponent4`/
  `AddComponents`) silently return null unless the component document is
  **already loaded in the session**. Mitigation: open the component first
  (with an explicit document type), insert, then close it; the component
  stays valid. This mirrors the official SOLIDWORKS VB example
  ("Insert steel disc component" in the BeltChainFeatureData page).
- `AddComponent5` places the component **centre** at the given coordinates;
  re-place with `SetTransformAndSolve2` if origin placement is wanted.
- `OpenDoc6` with type 0 (auto-detect) fails with
  `swInvalidFileTypeError` (1024) for `.sldprt`; pass the explicit type
  (1 = part, 2 = assembly, 3 = drawing).
- `IAssemblyDoc.ToolsCheckInterference2` raises `DISP_E_ARRAYISLOCKED`
  ("Memory is locked") when given a component array and finds nothing when
  given none. Mitigation: `IInterferenceDetectionMgr`:
  `IncludeMultibodyPartInterferences=True`,
  `TreatCoincidenceAsInterference=False`,
  `GetInterferenceCount()` -> `GetInterferences()` -> `IInterference.Volume`
  (m3) and `.Components`.
- `IComponent2.GetBox` returns null before the component's bodies are
  resolved; do not rely on it for placement.

## Drawings

- `IDrawingDoc.GetViews()` returns a nested tuple on this build; flatten it
  before wrapping the elements as `IView`.

## Feature API signatures (from this typelib, not the docs)

- `FeatureExtrusion3` takes **23 arguments**.
- `FeatureCut4` takes **27 arguments**.
- `FeatureRevolve2` takes **20 arguments**.
- `FeatureFillet3` takes **14 arguments**.
- `InsertFeatureChamfer` takes **8 arguments** (`Options=4`,
  `ChamferType=1` for equal-distance chamfers).
- `FeatureLinearPattern4` takes **20 arguments**; `FeatureCircularPattern5`
  takes **14**.
- `InsertRefPlane` takes **6 arguments** and reads its three references from
  selection marks 0/1/2.
- Many `Create*`/feature calls return `None` or `VARIANT` arrays whose
  truthiness is unreliable; success is judged by rebuild + `GetWhatsWrong` +
  measured mass properties, never by the return value alone.

## Environment

- Default templates exist at
  `C:\ProgramData\SOLIDWORKS\SOLIDWORKS 2026\templates` (`Part.PRTDOT`,
  `Assembly.ASMDOT`, `Drawing.DRWDOT`). Other folders named `templates`
  (for example the Inspection add-in) may exist and must not win discovery.
- `API SAFETY CHECKS ENABLED = 1` in HKCU General on this install.
- `Show Feature Names in Translated Language = 0`; the UI language setting is
  `Use English language = 0`. Never match on display names where an API token
  exists; plane selection falls back to enumerating `RefPlane` features.
