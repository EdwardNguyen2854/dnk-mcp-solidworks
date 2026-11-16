# SOLIDWORKS COM quirks log

Everything here was observed on this machine (SOLIDWORKS 2026 SP0.0, typelib
34.0, Python 3.12, pywin32 312) unless attributed otherwise. Each entry names
the mitigation in this codebase.

## Binding / dispatch

### Active-remodel findings (2026-09-27)

- Reproduced with `24-01-10.SLDPRT`; evidence and task scripts are under
  `artifacts/active-remodel`. `new_drawing` can report one model while
  `drawing_insert_standard_views(model=None)` inserts views of another open
  part. Pass the model path explicitly and verify every view's reference.
- `IView.SetDisplayMode3` and `GetDisplayMode2` use **swDisplayMode_e**, not
  `swViewDisplayMode_e`. The current drawing map uses the latter, so asking
  for hidden-lines-grayed passes 3 and renders shaded. Installed constants:
  wireframe=0, hidden-visible=1, hidden-removed=2, shaded=3. The tool's own
  reverse map can falsely confirm the requested mode; inspect the rendering.
- `InsertModelAnnotations` is not universally inert on 34.0.0: this task
  imported 18 dimensions from the original and 5 from the reconstructed part.
  The older no-import observations below are context-specific, not a blanket
  build limitation. Verify the before/after inventory on each document.
- `GetPartBox` is approximate. The remodel reported 135.0739 x 65.0739 x 85 mm;
  six `IBody2.GetExtremePoint` calls returned 135 x 65.000012 x 85 mm. Its
  mass/volume and 27-face topology closely match the original; it has one
  additional edge. Do not use the approximate box for precision acceptance.
- Default mass-property volume also has numerical sensitivity on this curved
  fixture. `IModelDocExtension.GetMassProperties2(2, 0, False)` (maximum
  accuracy, plain out-status value) changed original/remodel volumes from
  200016.234984/200016.444495 to 200014.289394/200014.497354 mm3, status 0.
  The independent analytic nominal was 200013.615903 mm3: a strict +/-0.5 mm3
  absolute check still failed. Record accuracy and numerical limits; do not
  declare exact equivalence from rounded mass-property agreement alone.
- Part `list_edges` reports untrimmed/evaluated points as endpoints on this
  fixture (some about 1000 mm outside the part). Actual `GetStartVertex` and
  `GetEndVertex` coordinates are correct. The drawing-edge path already uses
  vertices; the part path needs the same treatment.
- A counterbore's pilot may build before the second selection fails: reusing
  the original face dispatch after `SimpleHole2` can fail. In this task the
  caller also supplied sketch coordinates to an offset-based API; those are
  distinct issues. `face_point_from_offsets` uses the face minimum corner and
  ascending model axes, which the public schema should state explicitly.
- Sheet pseudo-views may have no `sheet_name`; `_named_view` filters them out
  even though annotation listing reports `Sheet1`. For the active sheet,
  `IDrawingDoc.GetFirstView` gives the wrapped sheet pseudo-view. The stock
  drawing in this task had duplicate title-block notes. Edit both inventories,
  enter `EditTemplate`, and finish with `EditSheet`; `INote.SetText` can return
  multiline text with CRLF, so normalize line endings for read-back checks.


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
  `GetDocuments()`. Measured 2026-09-26: the full path works for saved
  documents and is unambiguous; closure can complete **asynchronously**, so
  poll `GetDocuments()` for up to ~2 s before reporting a refusal. Two open
  documents that share a title cannot be closed individually — neither the
  title nor the full path disambiguates, and `ActivateDoc3` does not help.
  `IModelDoc2.SetSaveFlag` does not change `GetSaveFlag` on this build, but
  `CloseDoc` still discards the changes after it is called.
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

### Engineer-selection reads and entity references (measured 2026-10-01)

- `ISelectionMgr.GetSelectedObjectCount2(-1)` counts across marks;
  `GetSelectedObject6(index, -1)` returns the object and
  `GetSelectedObjectType3(index, -1)` its **swSelectType_e** (edges=1, faces=2,
  vertices=3). Use the type to pick the interface: QueryInterface to `IFace2`
  on an **edge** dispatch does not raise, so interface probing alone
  misclassifies; a member probe (`GetArea`/`GetCurve`/`GetPoint`) also works.
  Mitigation: `domain/references.py` keys the kind off the selection type.
- `IModelDocExtension.GetPersistReference3(entity)` returns a **VARIANT**
  (pywin32 `memoryview`, 367-389 bytes on the probe part), not a string;
  normalise with `bytes(bytearray(...))`.
  `GetObjectByPersistReference3(persistId, errorCode)` takes the VARIANT plus a
  plain out value (never a VARIANT) and returns `(object, error_code)` through
  `session.com_result`; error code 0 is success.
  `IsSamePersistentID(a, b)` gives exact identity between two references.
- Persist references survived, on the probe part: immediate round-trip,
  save-close-reopen, a topology-changing rebuild (a disjoint second body), and
  a through-cut of the referenced face itself (resolved to the same face with
  the hole: area 6000 -> 5921.46 mm2, volume 154000 -> 152037 mm3).
  Evidence: `scripts/probe_persist_reference.py` (17/17).
- A reference captured in an unsaved document and used after **Save As** fails
  the document-scope check: Save As changes title and path, which is a
  legitimate identity change. Capture references against a saved document
  (Datum's workflow binds proposals the same way).
- Fingerprint fallback: surface/curve, area/length, normal, bounding box, and
  edge endpoints/centres were unique (one match) on the probe part; matching
  uses small tolerances (`references.py`) and fails on zero or multiple
  matches. Do not widen tolerances without measuring ambiguity.

## Sketch editing (measured 2026-09-26)

- `IModelDoc2.SketchFillet2(Radius, KeepConstraints)` and
  `IModelDoc2.SketchChamfer(First, Second, Option)` are the calls that work;
  `ISketchManager.CreateFillet/CreateChamfer` return a segment without
  changing the geometry. Chamfer options: 0 = distance-angle (`First` is the
  angle in radians, `Second` the distance), 2 = equal distance. Both act on
  the current selection and can report nothing useful even on success — verify
  with the sketch fingerprint (segment count + total length).
- `ISketchManager.SketchTrim(Choice, X, Y, Z)` returns **False on success**;
  it acts on the selected segment and silently does nothing without one. The
  caller selects the target first and judges by the sketch fingerprint.
- `IModelDoc2.SketchMirror()` mirrors the selection about the selected
  centerline; entities and centerline are selected with mark 0.
- `ISketchManager.CreateSketchSlot(0, lengthType, width, p1, p2, p3, arcDir,
  addDim)` draws a straight slot; `swSketchSlotLengthType_e` chooses
  center-to-center (0) or full-length (1).
- `ISketchSegment.ConstructionGeometry` is a settable property; no
  `CreateConstructionGeometry` round-trip needed.
- Reopening a sketch: select the sketch feature
  (`SelectByID2(name, "SKETCH")`) then `InsertSketch(True)`; sketch features
  report `GetTypeName2()` == `ProfileFeature`.
- Sketch dimensions hang off the feature
  (`GetFirstDisplayDimension`/`GetNextDisplayDimension`).
  `IDisplayDimension.GetType()` carries `swDimensionType_e`;
  `IDimension.GetType()` returns 0 here. Drive by name with
  `IModelDoc2.Parameter(name)`; `SetSystemValue3(value, 2, None)` works and
  `SystemValue` reads back in metres/radians.

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
- `IComponent2.Select2` fails on mated or fully defined components. Select
  through `IComponent2.GetSelectByIDString()` +
  `SelectByID2(identifier, "COMPONENT", ...)` first, falling back to
  `Select2`.
- Mates are children of the `MateGroup` feature
  (`GetFirstSubFeature`/`GetNextSubFeature`); `GetSpecificFeature2()` wraps as
  `IMate2` for Type/Distance/Angle and `MateEntity(i)`.

## Drawings

- `IDrawingDoc.GetViews()` returns a nested tuple on this build; flatten it
  before wrapping the elements as `IView`.
- `ActivateView` is an `IDrawingDoc` member, not `IModelDoc2`; wrap the
  document before calling it or activation fails with `Member not found`.
- `InsertModelAnnotations3` *and* `4` return `None` and import nothing in
  unattended COM runs on this build (SW2026 SP0.0), even with the view
  selected and activated and the model dimensions verifiably marked for
  drawing (`IDisplayDimension.MarkedForDrawing = True`). DimXpert
  `IDrawingDoc.AutoDimension(1, 1, -1, 1, -1)` does work, so
  `drawing_auto_dimension` generates dimensions from view geometry instead.
- `IDrawingDoc.AutoDimension` dimensions the **selected** drawing view. With
  only `ActivateView` it silently dimensions a different view (measured: the
  last one created). Select the view first with
  `SelectByID2(name, "DRAWINGVIEW", 0, 0, 0, False, 0, None, 0)`, exactly like
  `InsertModelAnnotations3`.
- `IAnnotation.SetPosition(x, y, z)` (sheet metres) moves a drawing dimension
  line; `IDisplayDimension.Type2` is `swLinearDimension` (2) for both axes, so
  use `IDimension.DimensionLineDirection` (IMathVector) to tell horizontal
  from vertical. DimXpert stacks rows ~5-6 mm apart, which collides at the
  default 3.5 mm text height; `drawing_arrange_dimensions` re-spaces them.
- `IFeature.GetDisplayDimension(index)` is **1-based**: index 0 returns
  `None`, the first dimension is at index 1.
- `IModelDoc2.InsertNote` returns an untyped dispatch; wrap it as `INote`
  before calling `GetAnnotation`, or the late-bound call fails.
- To read annotations back: `IView.GetFirstAnnotation()` then
  `IAnnotation.GetNext()`. The annotation dispatch does **not** QueryInterface
  to `INote`; `IAnnotation.GetSpecificAnnotation()` does, and that is how note
  text is read back. `IAnnotation.GetPosition` returns metres in sheet space.

## Drawing sheets, views and appearance (measured 2026-09-26)

- `ISheet.GetProperties2()` returns `[paper size, template, scale1, scale2,
  first_angle, width, height]` with the dimensions in **metres**. The shipped
  default template starts as an unframed ANSI A (279.4 x 215.9 mm) sheet.
- A new drawing has **no sheet format** (no border or title block):
  `ISheet.GetSheetFormatName()` is empty, `SetSheetFormatName(Name)` returns
  `False`, `SetupSheet5`'s `TemplateName` (a `.slddrt` path) is ignored, and
  `ISldWorks.LoadFile4(slddrt, "r", None, errors)` returns `None` with
  `errors=1` even from a space-free path. This held for the stock ISO, DIN,
  GB and JIS sheet formats. What does work is passing the **paper code**
  (`swDwgPaperSizes_e`, which matches `swDwgTemplates_e` per size) as
  `SetupSheet5`'s `TemplateIn`: the stock frame is applied — ISO for A4-A0,
  ANSI for A-E — and `GetSheetFormatName` reports the generic
  `"Sheet Format1"`. This is how `new_drawing`, `drawing_add_sheet` and
  `drawing_set_sheet_format` frame sheets. GB/DIN/JIS artwork is therefore
  **not reachable** from COM on this build.
- `SetupSheet5(Name, PaperSize, TemplateIn, Scale1, Scale2, FirstAngle,
  TemplateName, Width, Height, PropertyViewName, RemoveModifiedNotes)`
  replaces the sheet's paper, scale and frame in place; existing views
  survive. Read `ISheet` again afterwards: the call can replace the sheet
  object and a stale wrapper reports the pre-call state. `FirstAngle` has no
  visible effect on the stock title block on this build.
- `CreateDrawViewFromModelView3` may **auto-scale** the new view to suit the
  sheet and updates the sheet scale to match (measured: an 80 x 40 mm plate
  on A3 lands at 2:1 with sheet scale 2:1, while an 85 x 65 mm part stays
  1:1). Read `IView.ScaleDecimal` back instead of assuming 1:1. Because of
  this, fixed centre distances between standard views can overlap; measure
  `IView.GetOutline()` and place the views from the outlines. `IView.
  ScaleDecimal` accepts an explicit scale per view and `ISheet.SetScale(n, d,
  True, True)` re-applies the sheet scale; the stock frame's `SCALE:` note
  then reads `SCALE:1:1`.
- Drawing dimension text: on SW2026 SP0.0 DimXpert display dimensions return
  an **empty** `IDisplayDimension.GetText(0..2)` and `GetLinkedText()`. The
  reliable read-back is `IDimension.Value` (document units, via
  `IDisplayDimension.GetDimension2(0)`) plus `IDimension.Tolerance`
  (`IDimensionTolerance.Type/GetMinValue/GetMaxValue/GetHoleFitValue/
  GetShaftFitValue`). `IDimensionTolerance.Type` uses `swTolType_e`
  (symmetric=4, bilateral=2, limits=3, fit=7); `SetValues(min, max)` takes
  signed values for bilateral and the absolute bounds for limits.
  **Units (corrected 2026-09-26): `SetValues` takes metres (system units) and
  `GetMinValue`/`GetMaxValue` return metres** — passing the tool's
  millimetres raw made a requested ±0.2 render as ±200.00. The tools convert
  at the API boundary. `SetFitValues` accepts a hole fit with an empty shaft
  string, so a hole-only callout "Ø10 H7" is possible (Ø10 H7 reads back as
  min 0.0 / max 0.015 mm).
- `InsertGeneralToleranceTableAnnotation` exists on this typelib for
  **parts/assemblies** (MBD context) and returns `None` on a drawing; the 2D
  drawing path therefore uses a general-tolerance note only when the design
  authority has supplied the applicable standard/class. Do not use the
  withdrawn combined ISO 2768-mK callout as a default. Its `X`/`Y` parameters
  are `long` (API units), unlike the double sheet coordinates elsewhere.
- Annotation attachment: `IView.SelectEntity(entity, append)` takes the
  entity from `IView.GetVisibleEntities2(None, 1)`. Those come back as
  untyped `IEntity` dispatches; `GetCurve` is only reachable after
  `binding.wrap(entity, "IEdge")` (late binding raises `Member not found`).
  Measured 2026-09-26: circle and line parameters come back in **model**
  metres (a hole at model x = 40 mm reads back as 40 mm), not sheet
  coordinates, so they identify the feature but do not place annotations.
  Line edges along the view's depth axis project to a point in x/y; report
  their true 3D length and out-of-plane `depth_mm` rather than a zero-length
  line (fixed 2026-09-26 — the side-view thickness edge used to read as
  0 mm).
- `IDrawingDoc.InsertDatumTag()` is void and uses the current selection; find
  the new tag by diffing type-2 annotations, then `IDatumTag.SetLabel(label)`
  and `GetLabel()` to write and verify the label.
- `IModelDoc2.InsertGtol()` returns the new `IGtol` dispatch.
  `SetFrameValues2(1, Tol1, Tol2, Datum1, Datum2, Datum3)` fills the frame
  text; `SetFrameSymbols(1, GCS, TolDia1, TolMC1, TolDia2, TolMC2, DatumMC1,
  DatumMC2, DatumMC3)` returns void but still applies. Verify through
  `GetFrameValues(1)` and `GetFrameSymbols(1)` -> `(GCS, TolDia1, TolMC1,
  TolDia2, TolMC2, DatumMC1, DatumMC2, DatumMC3)`; `GetText(0)` stays empty.
  GCS codes are in `swGtolGeomCharSymbol_e` (perpendicularity = 21,
  position = 23, flatness = 15, ...).
- `IModelDocExtension.InsertSurfaceFinishSymbol3` display: the roughness
  value belongs in the **`MaxRoughness`** string (12th argument) and reads
  back through `ISFSymbol.GetText(5)`. Parameter-to-index map measured on
  this build: `MachAllowance`=1, `OtherVals`=4, `MaxRoughness`=5,
  `MinRoughness`=6; `GetTextCount()` reports 0 for all of them, so read
  `GetText(0..6)` directly. **The value does not render** (corrected
  2026-09-26): every `GetTextHeightAtIndex(i)` is 0 mm and setting the
  document's `swDetailingSurfaceFinishTextFormat` or the annotation text
  format does not change it, so the symbol draws with a value-less placeholder
  line. `drawing_insert_surface_finish` stores and verifies the value; add a
  companion `Ra x.x` note next to the symbol until the build renders it.
- `ISheet.InsertRevisionTable2(UseAnchorPoint, X, Y, AnchorType, Template,
  Shape, AutoUpdateZoomCells)` returns `None` for anchor types 0 and 2-4 on
  the stock frames; `UseAnchorPoint=True` with **AnchorType=1** creates the
  table (stock columns ZONE, REV., DESCRIPTION, DATE, APPROVED). Read it back
  through `ISheet.RevisionTable` -> `IRevisionTableAnnotation` (`AddRevision`,
  `CurrentRevision`, `GetRowNumberForId`) and `ITableAnnotation` for
  `RowCount`/`ColumnCount`/`GetColumnTitle`. Cell writes go through
  `ITableAnnotation.SetText(Row, Column, Value)`; the `Text` member is the
  generated getter and rejects the extra value argument.
  Measured 2026-09-27: the anchored table pins its **bottom-left corner to the
  frame's inner top-right corner**, so it grows up and right across the border
  (and `SetPosition` is ignored while `ITableAnnotation.Anchored` is true).
  Set `Anchored=False`, read `GetColumnWidth`/`GetRowHeight` per
  row/column, then `SetPosition` the bottom-left to (corner - width,
  corner - height - 2 mm); `drawing_insert_revision_table` does this and
  reports `inside_frame`.
- BOM tables: `IView.InsertBomTable5(UseAnchorPoint=True, 0, 0, AnchorType=1,
  BomType, Configuration, "", False, 0, False, False)` works like the revision
  table. The **configuration** must match the view's referenced model: an
  empty string produces a **header-only** table (`RowCount` = 1), while the
  assembly's active configuration ("Default") lists all items. The put
  `IView.ReferencedConfiguration` has no getter on this build, so read the
  referenced model document's active configuration instead. `RowCount` and
  `ColumnCount` live on `ITableAnnotation` (wrap the returned dispatch);
  `IBomTableAnnotation.GetComponentsCount(row)` counts a row's components.
- Auto-balloons: `IDrawingDoc.CreateAutoBalloonOptions()` returns
  `IAutoBalloonOptions`; set `Style` (swBalloonStyle_e, circular = 1),
  `Size` (swBalloonFit_e, 3 chars = 3), `Layout` (swBalloonLayoutType_e,
  circle = 2), `ItemNumberStart`/`ItemOrder`, then `AutoBalloon5(options)`.
  The view must be selected and activated. Balloons read back as notes with
  `INote.IsBomBalloon`; their text stays `*` until the BOM table provides
  item numbers.
- Hole callouts: `IDrawingDoc.AddHoleCallout()` and `AddHoleCallout2(x, y, z)`
  both returned `None` on `SimpleHole2` holes, sketch/extruded-cut holes and
  the practice part's holes, with the circular edge selected and the view
  activated (measured 2026-09-26). Callout data comes from Hole Wizard
  features. `IFeatureManager.HoleWizard5/4` exist on this typelib, but every
  tested parameter set (ISO standard, plain hole, blind/through, several
  sizes and selection styles) created no feature, and the SOLIDWORKS session
  crashed in `mfc140u.dll` during that probing — do not fire invalid wizard
  calls in a loop; re-probe on a fresh session with a known-good parameter
  set first.
- Drawing view sketch coordinates are **sheet millimetres**, not model
  millimetres. `CreateLine` returns `None` silently for some sheet points
  once a view has been rescaled (measured after 2:1 -> 0.5:1: a line at the
  sheet origin fails while the same line at the view's centre succeeds), so
  draw reference geometry at the view's own position
  (`drawing_insert_section_view` / `drawing_insert_detail_view` already do).
- `NewSheet3(BSTR, long, long, double, double, VARIANT_BOOL, BSTR, double,
  double, BSTR)` adds a sheet and `ActivateSheet` makes one current. The new
  sheet becomes active.
- `CreateUnfoldedViewAt3(X, Y, Z, NotAligned)` creates a projected view. It
  projects from the **selected** view, not the active one: activating alone
  returns `None` silently. Select the parent with
  `SelectByID2(name, "DRAWINGVIEW", 0, 0, 0, False, 0, None, 0)` first.
  Corrected 2026-09-26: with the selection in place, **two** projections from
  one drawing succeeded; the earlier "only one projection per drawing" note
  was selection-state fallout. An earlier measurement still found projections
  returning `None` once a second sheet exists — add them before extra sheets.
  On SW2026 SP0.0, projected views read back their type, position, model path
  and configuration, but `GetOrientationName` is absent from the view listing.
  Verify first/third-angle orientation from the sheet setting, projection
  symbol, placement and raster; do not claim direct orientation read-back.
- `IDrawingDoc.ActiveDrawingView` can raise `Member not found` right after a
  view is created; treat it as advisory.
- `swCreateSectionViewAtOptions_e` on this typelib is NotAligned=1,
  OffsetSection=2, ChangeDirection=4, ScaleWithModel=8, Partial=16,
  DisplaySurfaceCut=32, **ExcludeFasteners=64**, CutSurfaceBodies=128 — the
  published notes that say 2 for fasteners are wrong. The ExcludedComponents
  VARIANT may be passed as `None`.
- Section and detail views take their boundary geometry from the current
  selection: activate the parent with `IDrawingDoc.ActivateView`, draw the
  line/circle (a view sketch may already be open), select the segment through
  `IEntity.Select4`, then call `CreateSectionViewAt5` / `CreateDetailViewAt4`.
- A drawing view sketch cannot be closed through the API on this build:
  `ISketchManager.InsertSketch(True)`/`(False)`, `IDrawingDoc.EditSketch` and
  `EditSketchOrSingleSketchFeature` all leave it open and `CreateLine` keeps
  appending to it. `SketchManager.ActiveSketch` reports the active view's
  sketch even when none is being edited, so it is not a state signal in
  drawings. `exit_sketch` reports `view_sketch: true`; the next section or
  detail command consumes the sketch.
- **Measured 2026-09-27: `CreateSectionViewAt5`/`CreateDetailViewAt4` need
  their boundary geometry in the view sketch's local space, not the sheet's.**
  A drawing view's sketch origin is the view's *centre*; a section line drawn
  with sheet coordinates lands one view-offset away, misses the geometry, and
  the call still succeeds - SOLIDWORKS returns a view labelled `section` with
  a normal outline that is never cut (DXF evidence: no bore contour, no
  bolt-hole voids, no hatching; `GetVisibleEntities2` returns the parent's
  axial circles only). `insert_section_view` and `insert_detail_view` now
  subtract `IView.Position` before drawing, and `insert_section_view` verifies
  the cut by read-back: a real section exposes line edges of its contour, so a
  view without them raises instead of shipping silently. No scale factor is
  involved - the conversion was verified at 1:1 and at 2:1 (the exported cut
  spans 100 mm and 200 mm respectively). Reproduced by
  `scripts/iso_flange_demo.py` (part FLG-2001). The same local space applies
  to `drawing_create_sketch`: geometry drawn there is view-local, so a manual
  boundary sketch is in the view's own millimetres, not the sheet's.
- Measured 2026-09-27: for a circular view whose holes run normal to the
  sheet, `AutoInsertCenterMarks2` adds exactly one mark (no per-hole marks),
  `insert_center_marks(selected_only=True)` fails with "SOLIDWORKS added no
  center marks", and `insert_centerlines` returns the same single annotation.
- `IView.Position` PROPPUT needs an `r8_array` of sheet metres;
  `IView.SetDisplayMode3(UseParent, Mode, Facetted, Edges)` and
  `IView.SetDisplayTangentEdges2(long)` are the style calls — there is no
  `TangentEdgeDisplay` property.
- `IView.AutoInsertCenterMarks2(InsertType, InsertOption, ...)` marks holes,
  fillets and slots (1|2|4) with linear, circular and base connection lines
  (1|2|8) and needs the view active. Marks read back as `center_mark`
  annotations. `InsertCenterMark3`/`InsertCenterLine2` act on the current
  selection, and the drawing-aware selection path is
  `IView.SelectEntity(entity, append)` — selecting the underlying model edges
  selects the model instead.
- `IModelDoc2.MaterialPropertyValues` (and `IFace2.MaterialPropertyValues`)
  take 9 doubles: R, G, B, ambient, diffuse, specular, shininess, transparency,
  emission. RGB is stored at 8-bit precision, so the read-back can differ by
  up to 1/255; both PROPputs need `r8_array`.
- `IModelDoc2.GetModelViewNames()` returns the localized orientation names in
  a fixed order (normal_to, front, back, left, right, top, bottom, isometric,
  trimetric, dimetric); `CreateDrawViewFromModelView3` silently creates
  nothing for a name it does not recognise, so resolve through the model
  rather than hard-coding English.

## Drawing annotation editing (measured 2026-09-26)

- Deleting an **annotation** (note or dimension): `IAnnotation.Select3(True,
  None)` returns `False` on this build and the delete is a no-op.
  `IAnnotation.Select(True)` (or `Select2(True, 0)`) selects, and
  `IModelDocExtension.DeleteSelection2(0)` removes. The delete return value is
  not a success signal — verify by comparing the view's annotation count
  before and after.
- Deleting a **view**: there is no view-delete API. `SelectByID2(name,
  "DRAWINGVIEW", 0, 0, 0, False, 0, None, 0)` + `DeleteSelection2` removes a
  model view (measured); fall back to the outline centre point when the name
  selection fails. The sheet pseudo-view does not appear in the active-sheet
  model-view list, so match the name against the sheet names first to protect
  it.
- Moving annotations: `IAnnotation.SetPosition(x, y, z)` moves notes and
  dimension text; `GetPosition` reads back within 0.1 mm. Positions are sheet
  metres (lower-left origin).
- Dimension text overrides: `IDisplayDimension.SetText(0, ...)`
  (`swDimensionTextAll`) is a **no-op** and `GetText(0)` always returns `""`.
  Prefix (1) and suffix (2) write and read back; `swDimensionTextParts_e` is
  prefix=1, suffix=2, callout-above=3, callout-below=4, prefix-declaration=5,
  suffix-declaration=6.
- Note text: `INote.SetText(BSTR)` replaces the whole text and reads back;
  property-link notes keep the raw `$PRP:"Name"` token in
  `INote.PropertyLinkedText`, so resolve it against the drawing's custom
  properties to report the displayed value.
- Text height: `IAnnotation.GetTextFormat()` **without** an argument raises
  "Type mismatch". Use `INote.GetTextFormat()` (or the indexed
  `IAnnotation.GetTextFormat(0)`), set `ITextFormat.CharHeight` (metres), then
  `INote.SetTextFormat(0, text_format)`; the height reads back through a fresh
  `GetTextFormat`. `add_note(height_mm=...)` silently failed on the broken
  no-arg call before this was measured.
- A stock ISO A3 sheet carries ~64 `note` annotations on the sheet view: the
  frame's zone letters and numbers. `list_drawing_annotations` reports them
  under `Sheet1`, so do not treat "sheet has notes" as user annotation
  leakage.
- `IModelDoc2.AddDimension2(x, y, z)` works in a drawing view: select one or
  two view edges with `IView.SelectEntity(entity, append)` (the same path as
  datum/GTol insertion), suppress `swInputDimValOnCreate` around the call, and
  the new dimension reads back through `list_dimensions` — two circular edges
  give a linear centre-distance dimension, one circle its diameter. Placement
  is sheet metres.
- `AddDimension2` between a **line and a circle** also measures to the circle
  **centre** (a hole 25 mm from an edge reads 25.00, not 20.00 to the
  tangent), so datum-referenced basic locating dimensions work directly; two
  parallel lines give their perpendicular distance.

## Feature API signatures (from this typelib, not the docs)

- Read-only typelib probe `python scripts/probe_api.py --enum
  swBodyOperationType_e` reports `SWBODYINTERSECT=15901`, `SWBODYCUT=15902`,
  `SWBODYADD=15903`, confirming (not disproving) the numeric `OPS` constants
  in `scripts/probe_combine_bodies.py`. This validates enum values only; it does
  not establish live operation success.
- `IFeatureManager.InsertCombineFeature(OperationType, MainBody, ToolVar)` takes
  3 arguments; `ToolVar` is a `VARIANT` array of `IBody2` dispatches. Live probe
  on SOLIDWORKS 2026 SP0.0 / typelib 34.0 (2026-10-03), using the overlapping
  rectangular-prism fixture in `scripts/probe_combine_bodies.py`, confirmed
  subtraction only: `VT_ARRAY | VT_DISPATCH` built with
  `win32com.client.VARIANT` succeeded, while tuple/list did not. The larger
  prism (1200 mm3) as MainBody minus the 400 mm3 overlap produced one `Combine1`
  body at 800 mm3 (expected 800; pass), bbox [5,2,0]-[15,12,12], 9 faces / 21
  edges. Rebuild succeeded and What's Wrong count was 0.
- In that same run, **add** returned no feature for all six script attempts
  (tuple, list, typed dispatch array, single dispatch, reversed main body, and
  selected bodies). Rebuild succeeded and What's Wrong count was 0, but the two
  source bodies remained unchanged: body count 2, measured 2200 mm3 vs expected
  1800 mm3 (+400; fail). **Common/intersect** likewise returned no feature for
  all six attempts; rebuild succeeded and What's Wrong count was 0, but the two
  source bodies remained unchanged: body count 2, measured 2200 mm3 vs expected
  400 mm3 (+1800; fail). A clean rebuild / zero What's Wrong does **not** mean
  add/common succeeded. A follow-up isolated probe on SOLIDWORKS 2026 SP0.0 /
  typelib 34.0 (2026-10-03), `scripts/probe_combine_isolated.py`, tested add and
  common once each in separate fresh scratch parts, using explicit MainBody plus
  one-element `VT_ARRAY | VT_DISPATCH` ToolVar and no preselection. Both calls
  returned no feature and added no feature-tree names. Each rebuild succeeded,
  What's Wrong count was 0, and the two source bodies remained unchanged (2
  bodies, 2200 mm3). Add expected 1800 mm3 (+400; fail); common expected 400 mm3
  (+1800; fail). Thus fresh-document isolation did not resolve either operation;
  a clean rebuild / zero What's Wrong still does not imply success. Investigate
  the API/operation contract further; at that probe stage the combine tool was
  withheld and add/common semantics were unresolved. A selected-body follow-up on 2026-10-03,
  `scripts/probe_combine_selected_bodies.py`, selected both bodies with
  `inspect.select_bodies` before the same single typed-array call (explicit
  MainBody, no retry variants), once per operation in separate scratch parts.
  Both selections succeeded (2 bodies selected), but add and common again
  returned no feature and no feature-tree delta; rebuild succeeded, What's Wrong
  count was 0, and both source bodies remained unchanged (2 bodies, 2200 mm3).
  Add expected 1800 mm3 (+400; fail); common expected 400 mm3 (+1800; fail).
  Thus preselecting both bodies does not resolve either operation. A direct
  interface probe, `scripts/probe_combine_direct_interface.py` (2026-10-03),
  wrapped `FeatureManager` as `IFeatureManager` and the tool body as `IBody2`,
  then attempted one call for add using
  `IInsertCombineFeature(15903, MainBody, 1, ToolBody)`. That call raised
  `com_error` (-2147352567): "Unable to read write-only property." The scratch
  document was discarded; per stop-on-error policy common was not called, so
  there are no direct-interface results for common. This is a call/signature or
  marshalling failure, not an operation measurement. A subtraction positive
  control (15902) through the same direct interface, with both bodies selected,
  explicit MainBody, ToolsCount=1, and wrapped IBody2 tool, raised the same
  HRESULT. Wrapper types were generated `IFeatureManager` and `IBody2` for
  typelib 34.0; `excepinfo` identified SOLIDWORKS Design: "Unable to read
  write-only property." (`argerror=None`). It stopped before feature/tree/rebuild/
  body/volume inspection; cleanup discarded the scratch part. This does not
  disprove the existing array-call subtraction result: the direct-interface
  candidate failed even for the positive control. A separate
  `IPartDoc.InsertCombineFeature` subtraction control
  (`scripts/probe_combine_ipartdoc_subtract.py`, 2026-10-04) succeeded: both
  bodies selected; wrappers were generated `IPartDoc` and `IBody2`; returned
  Python `True`; feature tree gained `Combine1`; rebuild succeeded, What's Wrong
  count 0, one body, volume 800 mm3 (expected 800; pass; bbox [5,2,0]-[15,12,12],
  9 faces / 21 edges). A repeat run on the same target reproduced the result
  exactly. This validates the IPartDoc method for subtraction only. A read-only
  definition inspection (`scripts/probe_combine_definition_readonly.py`, 2026-10-04)
  found `Combine1` type `CombineBodies`; `GetDefinition()` returned raw
  `win32com.client.CDispatch`, wrapped as generated
  `ICombineBodiesFeatureData`. Read-back: `OperationType=1`, `MainBody` returned
  an `IBody2` wrapper, `GetBodiesToCombineCount=1`, while `BodiesToCombine` read
  back as `None`. No `AccessSelections`, `ReleaseSelectionAccess`, or
  `ModifyDefinition` call was made; no COM error occurred. The read-only local
  typelib command `python scripts/probe_api.py --enum
  swCombineBodiesOperationType_e` reports Add=0, Subtract=1, Common=2. This is a
  distinct enum from `swBodyOperationType_e` used by the insertion methods:
  SWBODYADD=15903, SWBODYCUT=15902, SWBODYINTERSECT=15901. The OperationType=1
  read-back matches Subtract in the feature-data enum, not the insertion enum.
  Feature-data enum values were exercised in one controlled
  `ModifyDefinition` probe (`scripts/probe_combine_modify_definition.py`,
  2026-10-04): each fresh part first created a verified subtraction feature,
  then changed only `OperationType` and called `IFeature.ModifyDefinition(data,
  doc, None)` once, without selection-access calls. For Add=0, ModifyDefinition
  returned True, the Combine1 tree entry remained, rebuild succeeded, What's Wrong
  count was 0, body count 1, and volume was 1800 mm3 (expected 1800; pass; bbox
  [0,0,0]-[15,12,12], 11 faces / 27 edges). For Common=2, it returned True, the
  Combine1 tree entry remained, rebuild succeeded, What's Wrong count was 0, body
  count 1, and volume was 400 mm3 (expected 400; pass; bbox [5,2,0]-[10,10,10],
  6 faces / 12 edges). The prior `BodiesToCombine=None` with count 1 remains an
  unexplained readback limitation; no AccessSelections was used. These exact
  fixtures pass via ModifyDefinition; direct IPartDoc add/common insertion remains
  unsuccessful and is not the implemented route. The follow-up add/common probe, `scripts/probe_combine_ipartdoc_add_common.py` (2026-10-04),
  selected both bodies and made one `IPartDoc.InsertCombineFeature` call per
  operation in separate fresh parts. Both returned Boolean `False` with no new
  feature-tree names; rebuild succeeded, What's Wrong count was 0, and 2 unchanged
  bodies remained at 2200 mm3. Add expected 1800 mm3 (+400; fail); common expected
  400 mm3 (+1800; fail). Those direct IPartDoc calls failed; do not infer success
  from their Boolean or clean rebuild. The separate ModifyDefinition path above
  passes these exact fixtures and is the measured basis for the typed tool; support
  remains limited to those fixture geometries. Probe history is in
  `scripts/probe_combine_bodies.py`. The typed
   extended-tier `combine_bodies` tool is registered and follows this measured path: subtract
   calls `IPartDoc.InsertCombineFeature(15902, ...)`; add/common seed that verified
   subtraction and alter only `ICombineBodiesFeatureData.OperationType` (0/2) via
   one `ModifyDefinition`. Its mocked unit tests exercise dispatch, validation,
   postconditions and rollback without SOLIDWORKS. `scripts/acceptance_combine_bodies.py`
   now runs the registered MCP tool over stdio against fresh fixtures: subtract 600 mm3,
   add 1800 mm3 and common 400 mm3 all passed (26/26 checks, 2026-11-16), with one body,
   one `Combine1` feature, clean rebuild and What's Wrong 0; an equal-index request was
   rejected as `INVALID_PARAMETER` with the two source bodies unchanged at 2200 mm3.
   `GetBodies2` enumeration order did not follow creation order in that run (the second
   prism came back at index 0), so callers must resolve indices from `list_bodies` and
   the tool must keep using the same enumeration for validation and selection. This
   acceptance does not widen the evidence: only the overlapping rectangular-prism
   fixture and exact operations/volumes above were live-measured on SW2026 SP0.0 /
   typelib 34.0. Do not generalize support to other geometries, versions, or
   configurations until separately live-accepted.
- `FeatureExtrusion3` takes **23 arguments**.
- `FeatureCut4` takes **27 arguments**.
- Reference end conditions on `FeatureExtrusion3` / `FeatureCut4` require the
  profile sketch selected with mark 0 and the target selected with mark 1.
  `UpToSurface=4`, `OffsetFromSurface=5`, `UpToVertex=3`, and `UpToBody=7`
  build and pass exact volume checks. `OffsetReverse1=True` extends past the
  reference (plane z=30, offset +5 -> z=35); False pulls back to z=25. The
  public offset convention is positive = beyond, negative = back toward the
  sketch. `IBody2.Select2(append, ISelectData)` is required for body targets.
- `FeatureBossThin2` takes the first 24 arguments of the thin-feature call;
  `FeatureCutThin2` takes 29 here. Both need `Dir=True` in the measured
  working calls. Preserve the just-closed sketch selection: clearing it makes
  both thin APIs return/build nothing. `RevThinDir` 0/1/2 means outward / inward
  / mid; the r=20, t=2, depth=10 ring checks read 2638.94 / 2387.61 / 2513.27
  mm3 respectively.
- `FeatureRevolve2` takes **20 arguments**.
- `FeatureRevolveCut2` takes **10 arguments**; the angle is argument 1 and a
  construction centerline in the newest sketch supplies the axis.
- `FeatureFillet3` takes **14 arguments**.
- Face fillet is `Ftyp=2` with the two faces selected at mark 0. It matched the
  hand-calculated cube-corner blend volume. Variable-radius `FeatureFillet3`
  builds a feature but the passed radii do not match the expected uniform or
  end-radius geometry; `IVariableFilletFeatureData2.GetRadius` raises an
  internal application error on the tested feature. Keep variable-radius,
  asymmetric and full-round variants withheld until read-back is reliable.
- `InsertFeatureChamfer` takes **8 arguments** (`Options=4`,
  type 1 is angle-distance (45 degrees gives equal-distance); type 2 is
  distance-distance. Type 16, although named EqualDistance in the typelib,
  builds a feature with no volume change in tested parameter combinations.
- `IModelDoc2.InsertDome(height, reverse, elliptic)` returns void and needs its
  selected face at mark 1; mark 0 silently builds nothing. A circular face
  produced the spherical-cap volume `pi*h/6*(3a^2+h^2)` exactly.
- `InsertCosmeticThread2(Type, first_double, second_double, Note)` has
  misleading typelib names: the first double reads back as `Diameter`, and the
  second as `BlindDepth`. On a tapped edge the cosmetic feature nests below the
  hole rather than appearing in the top-level feature walk; check the returned
  feature definition. A single thread rebuilt with zero What's Wrong errors.
- `FeatureLinearPattern5` takes **22 arguments** (`FeatureLinearPattern4`
  takes 20); use pattern 5 on this build.
- `FeatureCircularPattern5` takes **14 arguments**.
- `InsertMirrorFeature2` takes **5 arguments**
  (`BMirrorBody, BGeometryPattern, BMerge, BKnit, ScopeOptions`).
- `InsertRefPlane` takes **6 arguments as three (constraint, value) pairs**
  from `swRefPlaneReferenceConstraints_e` (distance=8, angle=16,
  midplane=128, coincident=4, parallel=1, flip=256); the reference entities
  themselves come from selection marks 0/1/2.
- Many `Create*`/feature calls return `None` or `VARIANT` arrays whose
  truthiness is unreliable; success is judged by rebuild + `GetWhatsWrong` +
  measured mass properties, never by the return value alone.
- `InsertMultiFaceDraft(Angle, FlipDir, EdgeDraft, PropType, IsStepDraft,
  IsBodyDraft)`: neutral reference = mark 1, drafted faces = mark 2.
- Sweep: profile = mark 1, path = mark 4; `InsertProtrusionSwept4` takes 20
  arguments, `InsertCutSwept5` 22.
- Loft is spelled "blend" in the API: every profile sketch is selected with
  mark 1, in order; `InsertProtrusionBlend2` takes 18 arguments,
  `InsertCutBlend` 12.
- `SimpleHole2(Dia, Sd, Flip, Dir, T1, T2, D1, D2, ...)` takes no sketch: the
  hole centre is the **ISelectData X/Y/Z of the face selection** (the official
  example's pattern). A sketch planted on a face has an unpredictable origin,
  so sketch-point placement lands off-centre.
- `InsertRib` builds nothing on this build. Every documented combination
  (parallel/normal to sketch, two-sided, profile on a datum plane and on an
  offset midplane, sketch selected by name and by `IFeature.Select2`) returned
  void with no new feature and no rebuild error; the session later dropped its
  COM connection. The `rib` tool is withheld until a later build re-probes it.
- `IFeature.SetSuppression2` is not used; `IModelDoc2.EditSuppress2` /
  `EditUnsuppress2` act on the selected feature and are verified through
  `IFeature.IsSuppressed`.
- `IModelDoc2.InsertAxis2(True)` returns a boolean and builds the axis from
  the current selection (planar face, straight edge, two planes or two
  points); the new feature type is `RefAxis`.

## Single-ended cuts (FeatureCut4)

- The signature is `(Sd, Flip, Dir, T1, T2, D1, D2, ...)`. For a
  single-ended cut `Dir` must be `True` to cut **into** material; with
  `Dir=False` the cut points into empty space and `FeatureCut4` returns
  `None` without a rebuild error. The old code passed `False` always, which
  is why only `through_all_both` cuts worked.
- Argument 2 (`Flip`) is the UI's "flip side to cut" (remove everything
  outside the profile), not a direction flag.
- Which way a sketch plane faces is not predictable, so a cut that removes
  nothing is retried with the opposite `Dir`; the result reports
  `reversed_automatically: true`.

## Patterns, mirror and reference planes

- Selection marks these APIs actually read:
  - linear pattern: direction 1 = mark 1, direction 2 = mark 2, seed features
    = mark 4; the `DName1`/`DName2` strings stay empty when the direction
    entities are selected.
  - circular pattern: axis = mark 1 (straight edge or cylindrical face),
    seed features = mark 4.
  - mirror: mirror plane = mark 2, features = mark 1.
  - `InsertRefPlane`: first/second/third reference = marks 0/1/2.
- `InsertRefPlane` returns an untyped dispatch that does **not**
  QueryInterface to `IFeature` (`wrap` silently returns the raw dispatch and
  `GetTypeName2` then raises `Member not found`). Find the new plane by
  diffing the feature-tree names before/after, exactly like
  `InsertFeatureShell`.
- A reference plane created with a `name` argument is renamed through the
  normal `IFeature.Name` path; the tree diff is what makes the rename safe.

## Measurement

- `IModelDocExtension.CreateMeasure` and `IMeasure.Calculate`: with early
  binding, `Calculate` takes one `in` VARIANT; passing `None` measures the
  current selection. Readings of -1 mean "not applicable" to the selection.
  Select the entities first and clear the selection afterwards.
- `IVertex.GetPoint()` returns the model-space position in metres.
- `list_vertices` indices follow `GetBodies2 -> GetVertices` order, the same
  order `select_vertices` uses.

## Diagnostics and review drawing updates (2026-09-28)

- `swDisplayMode_e` values on typelib 34.0 are wireframe=0,
  hidden-lines-grayed=1, hidden-lines-removed=2, shaded=3,
  faceted-wireframe=4, faceted-hidden-grayed=5, faceted-hidden-removed=6,
  shaded-with-edges=7, default=8. `swViewDisplayMode_e` is a different enum.
  Read `IView.GetDisplayMode2` after `SetDisplayMode3`; matching the wrong enum
  can report success while rendering a different mode.
- `IModelDocExtension.GetMassProperties2(Accuracy, Status, UseSelected)` is
  `GetMassProperties2(2, 0, False)` for maximum accuracy on this build. Pass a
  plain integer for the status out parameter and split it with
  `session.com_result(result, 1)`. The returned array starts with SI centre
  of mass X/Y/Z, volume, area, then mass (the documented array order);
  status 0 was successful in the measured fixture.
- `IBody2.GetExtremePoint(X, Y, Z, OutX, OutY, OutZ)` returns a Boolean plus
  three metre-valued out coordinates. Query +/- each model axis per solid
  body and combine extrema; this is more precise than `GetPartBox`.
- `IEdge.GetStartVertex`/`GetEndVertex` provide trimmed topological endpoints.
  A closed edge can return no distinct endpoints; report its closed state
  instead of evaluating an untrimmed curve at arbitrary parameters.
- Face-offset placement uses the face bounding-box minimum corner as origin,
  with ascending model X/Y axes in millimetres independent of normal sign.
  `GetTessTriangles(True)` is in system metres and can screen whether a point
  lies on trimmed tessellated face regions; it remains tessellation-based.
- `swConstrainedStatus_e` on this typelib is unknown=1, under=2, fully=3,
  over=4, no-solution=5, invalid-solution=6, autosolve-off=7.
  `ISketch.ModelToSketchTransform` returns `IMathTransform`; the transform
  `ArrayData` contains the rotation, translation, and scale. `ISketch` exposes
  no degrees-of-freedom count accessor on this build, so report DOF as
  unavailable rather than deriving it from entity counts.
- `IFeature.GetDefinition()` returns an untyped `IDispatch`. The measured
  extrude/cut parameter path is to wrap it as `IExtrudeFeatureData2` and call
  `GetDepth(True/False)`; the values are metres. The live boss created by
  `FeatureExtrusion3` reports `GetTypeName2() == "Extrusion"`, so the diagnostic
  dispatch includes that type in addition to Boss/Cut aliases. Other feature definitions
  remain unavailable until their interface and access sequence are probed.
- A typelib-only inspection suggested `IView.ReferencedConfiguration` was
  write-only, but live acceptance on 34.0.0 read `Default` back successfully
  for all three inserted standard views. Prefer actual view readback and
  report unavailable only when the getter fails. `GetReferencedModelName`
  provides the view's model identity.
- Closed circular edges may have no vertices. Countersink/thread edge lookup
  must use `ICurve.CircleParams` centre/axis/radius, not `start_mm`. Live
  modelling-depth acceptance caught this dependency after endpoint repair.
- Revision-table extents can be measured from the `IAnnotation` position and
  `ITableAnnotation` row/column sizes. The annotation position is the
  bottom-left on this build; convert the table dimensions from metres.
- `HoleWizard5` exists in typelib 34.0, but the exploratory call crashed in
  `mfc140u.dll` on SOLIDWORKS 2026 SP0.0. Native Hole Wizard creation is
  withheld until a safe known-good acceptance path exists. Current compound
  hole features are geometry-only and have no native callout semantics.
- PDF text extraction is not sufficient evidence for diameter or degree
  glyph rendering. Verify meaning through SOLIDWORKS annotation data and a
  rendered raster. The MCP server already serializes screenshot payloads as
  image content blocks; do not move image base64 into JSON text or logs.

## Environment

- Default templates exist at
  `C:\ProgramData\SOLIDWORKS\SOLIDWORKS 2026\templates` (`Part.PRTDOT`,
  `Assembly.ASMDOT`, `Drawing.DRWDOT`). Other folders named `templates`
  (for example the Inspection add-in) may exist and must not win discovery.
- `API SAFETY CHECKS ENABLED = 1` in HKCU General on this install.
- `Show Feature Names in Translated Language = 0`; the UI language setting is
  `Use English language = 0`. Never match on display names where an API token
  exists; plane selection falls back to enumerating `RefPlane` features.
