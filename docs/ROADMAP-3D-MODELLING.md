# Roadmap: extending the 3D modelling surface

Status (checked 2026-10-04): Wave 1 is implemented and previously live-verified
(2026-09-27); Wave 2 is in progress. The unit suite passes. On SOLIDWORKS 2026
SP0.0 / typelib 34.0, subtraction on the overlapping-prism fixture passed via
`IPartDoc.InsertCombineFeature` (true, Combine1, one body, 800 mm3 expected and
measured, clean rebuild, What's Wrong 0). The same IPartDoc method returned false
for add and common in separate scratch parts, with no feature-tree changes; both
rebuilds were clean with What's Wrong 0, but two source bodies remained at 2200
mm3 (expected 1800 for add, 400 for common), so both direct insertion calls failed.
However, a separate controlled ModifyDefinition path changed only the feature-data
OperationType from a subtraction seed: add enum 0 produced one body at exactly
1800 mm3; common enum 2 produced one body at exactly 400 mm3. Both ModifyDefinition
calls returned True, retained Combine1, rebuilt cleanly, and had What's Wrong 0.
The feature-data enum values (Add=0/Subtract=1/Common=2) differ from insertion
codes; read-only typelib enum values `SWBODYINTERSECT=15901`, `SWBODYCUT=15902`,
and `SWBODYADD=15903` validate only the latter. Thus the ModifyDefinition route passes these fixtures, and the typed extended-tier
`combine_bodies` tool implements the measured sequence with mocked unit coverage
(including rollback). The registered tool is now live-accepted through the MCP
stdio path: `scripts/acceptance_combine_bodies.py` passed 26/26 checks on
2026-11-16 (subtract 600 mm3, add 1800 mm3, common 400 mm3; one body, one
`Combine1`, clean rebuild, What's Wrong 0; equal-index request rejected with the
source bodies unchanged). This does not broaden fixture evidence: only the exact
overlapping rectangular prisms, operations and volumes above were live-verified on
SW2026 SP0.0 / typelib 34.0. Other geometry, versions, and configurations remain
unverified; do not infer general combine support without separate live acceptance.
Details and probe paths are in `docs/COM-QUIRKS.md`. `combine_bodies` is the first
registered Wave 2 tool. Wave 1's 26/26 live and
43/43 part-acceptance results are historical, not rerun here.

Scope: **part modelling**. Drawings and the assembly mate surface are already
covered; assembly-level modelling (component patterns, exploded views) is folded
into Wave 6 as an optional add-on.

## Principles (unchanged from AGENTS.md)

- Typed, fixed tool surface; no generic COM-invoke escape hatch.
- Probe the shipped typelib before coding; record the answer in
  `docs/COM-QUIRKS.md` the same day.
- Never trust feature return values. Every mutation is judged by rebuild +
  `GetWhatsWrong` + measured mass properties / bounding box / body count.
- Every live check compares against a hand calculation, not against "it built".
- Each wave ends with: probe script, unit tests for pure argument mapping,
  live acceptance checks, COM-QUIRKS entries, README/AGENTS/CHANGELOG sync.

## Measured feasibility snapshot

Entry points confirmed on this typelib (full signatures available via
`python scripts/probe_api.py --method IFeatureManager <Name>`):

| Area | Entry point | State |
|---|---|---|
| Extrude end conditions | `IFeatureManager.FeatureExtrusion3` / `FeatureCut4` | measured and shipped: `UpToSurface=4`, `OffsetFromSurface=5`, `UpToBody=7`, `UpToVertex=3`; profile mark 0, reference mark 1. `UpToSelection=10` remains deferred |
| Cut revolve | `IFeatureManager.FeatureRevolveCut2` (10 args) | measured and shipped; centerline selection matches `revolve` |
| Thin boss/cut | `FeatureBossThin2` / `FeatureCutThin2` | measured and shipped; `Dir=True`, `RevThinDir` outward/inward/mid = 0/1/2 |
| Fillet variants | `FeatureFillet3(Options, R1, R2, Rho, Ftyp, ...)` | constant and face fillets shipped; variable-radius read-back/semantics are unreliable on this build and full-round/asymmetric remain deferred |
| Chamfer variants | `InsertFeatureChamfer(Options, Type, ...)` | measured and shipped: type 1 angle-distance (45° for equal), type 2 distance-distance; typelib type 16 is a no-op in tested calls |
| Cosmetic thread | `InsertCosmeticThread2(long, double, double, BSTR)` | measured and shipped; `ICosmeticThreadFeatureData` read-back is clean, and the feature nests under the hole |
| Hole Wizard | `IFeatureManager.HoleWizard5` (27 args), `IWizardHoleFeatureData2` | present but **known-broken/crashing** on this build (see COM-QUIRKS); one-shot spike only |
| Dome | `IModelDoc2.InsertDome(double, VARIANT_BOOL, VARIANT_BOOL)` | measured and shipped; face selection must use mark 1 |
| Combine bodies | `IFeatureManager.InsertCombineFeature(long, IBody2*, VARIANT)` | present; body selection via `IBody2.Select2(append, ISelectData)` |
| Split bodies | `FeatureManager.PreSplitBody2` / `PostSplitBody2` | present, two-phase, unprobed |
| Move/copy body | `FeatureManager.InsertMoveCopyBody2` (12 args) | present |
| Scale body | `FeatureManager.InsertScale(short, VARIANT_BOOL, double, double, double)` | present |
| Delete / move / replace face | `IModelDoc2.InsertDeleteFace2`, `FeatureManager.InsertMoveFace3`, `IModelDoc2.InsertFeatureReplaceFace` | present; `IMoveFaceFeatureData` / `IDeleteFaceFeatureData` present |
| Insert part bodies | `IPartDoc.InsertPart3(BSTR, long, BSTR)` | present |
| Configurations | `IConfigurationManager.AddConfiguration2`, `IModelDoc2.GetConfigurationNames` / `ShowConfiguration2` / `DeleteConfiguration2`, `IConfiguration.Get/SetParameters`, `IConfigurationManager.SetConfigurationParams` | present |
| Per-config features | `IFeature.SetSuppression2(long, long, VARIANT)` | present |
| Equations | `IEquationMgr.Add3` / `Equation(i)` / `GetCount` / `EvaluateAll` / `GlobalVariable` | present |
| Sketch/curve-driven patterns | `FeatureManager.FeatureLocalSketchDrivenPattern(long)`, `FeatureLocalCurveDrivenPattern(...)`, `FeatureSketchDrivenPattern(...)`, `InsertVaryInstanceOverride/Increment` | present, unprobed |
| Helix / projected curve / split line | `InsertHelix` (10 args), `InsertProjectedSketch2`, `InsertSplitLineSil/Project/Intersect` | present, unprobed |
| Coordinate system | `FeatureManager.InsertCoordinateSystem(VARIANT_BOOL, VARIANT_BOOL, VARIANT_BOOL)` | present |
| Sheet metal | `InsertSheetMetalBaseFlange2` (20 args), `InsertSheetMetalEdgeFlange2`, `InsertSheetMetalMiterFlange`, `InsertSheetMetalHem2`, `InsertSheetMetalJog`, `InsertSheetMetalCornerTrim`, `InsertSheetMetalBreakCorner`, `InsertSheetMetalFold/Unfold`, `GetFlatPatternFolder`, `IPartDoc.ExportFlatPatternView`, `ICustomBendAllowance` | present, large unprobed slice |
| Surfaces | `FeatureExtruRefSurface3`, `InsertRevolvedRefSurface`, `InsertPlanarRefSurface`, `Pre/PostTrimSurface`, `InsertUntrimSurface2`, `FeatureBossThicken` / `FeatureCutThicken`, `InsertFillSurface2`, `InsertRuledSurfaceFromEdge2`, `InsertFreeform2` | present; **knit** method name not found (probe) |
| Weldments | `InsertStructuralWeldment5`, `InsertWeldmentTrimFeature2`, `InsertFilletBeadFeature3` (weld bead), `InsertWeldmentCutList2` | present, needs profile library check |
| Assembly modelling | `IAssemblyDoc.InsertDerivedPattern`, `MirrorComponents3`, `CreateExplodedView` / `ShowExploded2`, `AddExplodeStep` | present, unprobed |

## Wave 1 — Feature depth (recommended first)

Why first: mostly additive to `domain/features.py`, highest ratio of modelling
power to risk, and it fills the gaps an agent hits immediately when building
mechanical parts.

| Tool | Entry point | Notes |
|---|---|---|
| `boss_extrude` / `cut_extrude` (extend) | `FeatureExtrusion3` / `FeatureCut4` | shipped: `up_to_surface`, `offset_from_surface`, `up_to_body`, `up_to_vertex`; profile mark 0, reference mark 1. `up_to_selection` deferred |
| `revolve_cut` | `FeatureRevolveCut2` | shipped; centerline selection matches `revolve`, hand-calculated ring cut |
| `thin_extrude` | `FeatureBossThin2` / `FeatureCutThin2` | shipped; thickness + outward/inward/mid side + cut flag; hand-calculated ring volumes |
| `fillet` (extend) | `FeatureFillet3` | shipped: constant and face fillets. Variable-radius semantics/read-back unreliable; full-round and asymmetric deferred |
| `chamfer` (extend) | `InsertFeatureChamfer` | shipped: equal (type 1 at 45°), angle-distance and distance-distance; typelib type 16 is a measured no-op |
| `cosmetic_thread` | `InsertCosmeticThread2` | shipped; circular edge selection and `ICosmeticThreadFeatureData` read-back |
| `counterbore_hole` | recipe: two `SimpleHole2` features | shipped; explicit pilot/counterbore diameters/depths; hand-calc volume |
| `countersink_hole` | recipe: `SimpleHole2` + chamfer | shipped; included angle and diameter; hand-calc frustum volume |
| `tapped_hole` | recipe + `InsertCosmeticThread2` | shipped; explicit drill diameter supported; default drill approximation is diameter minus pitch |
| `dome` | `IModelDoc2.InsertDome` | shipped; face mark 1, circular-face spherical-cap volume |
| `hole_wizard` | `HoleWizard5` | **spike only.** One known-good call in a fresh session; if it builds, ship the tool; if not, keep the recipes and update COMP-QUIRKS. Do not loop failing calls |
| `rib` | `InsertRib2` | one retry on this build while the probe session is open; stay withheld if unchanged |

Acceptance: `scripts/acceptance_modelling_depth.py` runs 26 hand-calculated
checks; `scripts/probe_feature_depth.py` and its follow-up probes retain the
measured marks/options for later SOLIDWORKS builds.

## Wave 2 — Multi-body and direct editing

Why: multi-body modelling is the missing half of part modelling; direct editing
is how an agent repairs imported or awkward geometry.

- `combine_bodies` (add / subtract / common) — implemented as an extended-tier
  typed tool. Subtract uses `IPartDoc.InsertCombineFeature(15902, ...)`; add/common
  seed subtraction and change only feature-data `OperationType` (0/2) via
  `ModifyDefinition`. Registered-tool live acceptance passes 26/26
  (`scripts/acceptance_combine_bodies.py`); exact live fixture evidence and
  general-support limits are recorded above and in `docs/COM-QUIRKS.md`.
- `split_bodies` — `PreSplitBody2` / `PostSplitBody2`; probe the two-phase
  contract; optionally save bodies; verify volume conservation and body count.
- `move_copy_body` — `InsertMoveCopyBody2`; translate/rotate, copy; read back
  the body box.
- `scale_body` — `FeatureManager.InsertScale`; probe the `kind` enum; verify
  box scales linearly and volume by the cube.
- `delete_face` — `IModelDoc2.InsertDeleteFace2` (and `IBody2.DeleteFaces5` as
  fallback); probe heal options; verify face count + volume delta.
- `move_face` — `InsertMoveFace3`; probe option/mark semantics; verify bbox.
- `replace_face` — `IModelDoc2.InsertFeatureReplaceFace`; verify volume against
  hand calc of the replacement.
- `insert_part` — `IPartDoc.InsertPart3`; place an external `.sldprt` as new
  bodies or locate it; verify total mass = sum of parts.
- `delete_body` — `FeatureManager.InsertDeleteBody2`.

Shared infrastructure already delivered in Wave 1: `inspect.select_bodies`
uses `IBody2.Select2(append, ISelectData)` with `CreateSelectData`.

## Continuation point

Wave 1 is complete; continue with **Wave 2 — Multi-body and direct editing**.
The initial `InsertCombineFeature` probe and isolated follow-up are recorded above
and in `docs/COM-QUIRKS.md`. Subtraction passed its analytic volume check, but add
and common returned no feature and left both source bodies unchanged. Fresh-document
calls reproduced that result with explicit MainBody and typed one-element ToolVar;
selecting both bodies did not change it. The read-only enum probe confirms numeric
constants. A direct `IFeatureManager.IInsertCombineFeature(15903, MainBody, 1,
ToolBody)` add call and its subtraction positive control both raised `com_error`
(-2147352567, "Unable to read write-only property") before measurement; do not
infer an operation failure from that interface. The alternate
`IPartDoc.InsertCombineFeature` subtraction control returned True, added Combine1,
rebuilt cleanly, and produced one body at the expected 800 mm3; a repeat run
reproduced the result. Read-only `Combine1.GetDefinition()` inspection wrapped as
`ICombineBodiesFeatureData`: `OperationType=1`, `MainBody` returned an `IBody2`
wrapper, `GetBodiesToCombineCount=1`, but `BodiesToCombine` returned `None`. No
selection access or definition modification was used. Local typelib inspection
reports `swCombineBodiesOperationType_e`: Add=0, Subtract=1, Common=2, distinct
from insertion-method `swBodyOperationType_e` codes Add=15903, Cut=15902,
Intersect=15901. A controlled `ModifyDefinition` probe
(`scripts/probe_combine_modify_definition.py`) tested the feature-data enum on a
known-good subtraction feature, changing only `OperationType` without selection
access. Add=0 returned True and produced one body at 1800 mm3 expected/measured;
Common=2 returned True and produced one body at 400 mm3 expected/measured. Both
had unchanged feature-tree names, clean rebuild, and What's Wrong 0. Thus the
feature-data edit path passes these exact fixtures, unlike direct
`IPartDoc.InsertCombineFeature` add/common (which both returned False and left two
bodies at 2200 mm3). The `BodiesToCombine=None` readback with count 1 remains
unresolved; do not infer an empty tool list. The typed tool implements the verified
sequence, has mock coverage, and passed registered-tool live acceptance 26/26 on
2026-11-16; live evidence remains limited to these exact fixture geometries on
typelib 34.0, not broad geometry support. Next Wave 2 step: probe
`PreSplitBody2` / `PostSplitBody2` in an isolated script, then verify volume
conservation and body count before shipping a typed tool.
Do not begin Wave 3 until Wave 2 findings and acceptance scope are recorded.

Wave 1 deliberately left these items deferred: `UpToSelection=10`,
variable-radius/asymmetric/full-round fillets, Hole Wizard (crash risk), and
rib (no feature built on the tested build). Revisit only as separate, isolated
probes; never include Hole Wizard in a looping probe.

## Wave 3 — Parametric state (configurations + equations)

Why: turns one-off models into families. This is the modelling half of the
"batch/plan execution" milestone already flagged in PRIOR-ART.

- `list_configurations` — `GetConfigurationNames` + active name.
- `create_configuration` — `IConfigurationManager.AddConfiguration2`; probe
  options (child/derived flags) and comment/description read-back.
- `activate_configuration` — `ShowConfiguration2` + rebuild + evidence.
- `delete_configuration` — `DeleteConfiguration2`.
- `configure_feature` — per-config suppression via `IFeature.SetSuppression2`;
  probe `Config_opt` constants.
- `configure_dimension` — per-config dimension values; probe
  `IConfigurationManager.SetConfigurationParams` array marshalling (PTR args)
  against `IConfiguration.SetParameters`; the equation route is the fallback.
- `add_equation` / `list_equations` / `delete_equation` /
  `evaluate_equations` — `IEquationMgr.Add3(Index, Equation, Solve,
  WhichConfigurations, ConfigNames)`; probe index base and `GlobalVariable`.
- Design tables (`IDesignTable`) are deliberately deferred to a later release.

Acceptance: a two-configuration box where `A`/`B`/`C` differ per config; every
count reads back volume = A*B*C after activation, suppression flips per config,
and an equation (`"D" = "A" * 2`) drives a dimension.

## Wave 4 — Patterns, curves, references

- `sketch_driven_pattern` — `FeatureLocalSketchDrivenPattern` /
  `FeatureSketchDrivenPattern`; sketch points give the instances.
- `curve_driven_pattern` — `FeatureLocalCurveDrivenPattern`; probe references.
- `helix` — `IModelDoc2.InsertHelix` (10 args: height, pitch/revs, taper,
  direction, start angle); verified by bounding box + volume after sweep.
- `projected_curve` — `InsertProjectedSketch2`; two sketches, one projection
  direction; verify via downstream sweep or bbox.
- `split_line` — silhouette / projected / intersection variants
  (`InsertSplitLineSil`, `InsertSplitLineProject`, `InsertSplitLineIntersect`).
- `coordinate_system` — `InsertCoordinateSystem`; selection combinations
  (vertex+edges / planes).
- Optional: `fill_pattern` (`FeatureFillPattern`), `vary_pattern`
  (`InsertVaryInstanceOverride`), `insert_3d_sketch` (`ISketchManager.Insert3DSketch`).

Acceptance: instance counts + total-volume multiples; helix bbox; split line
face-count delta; coordinate-system read-back transform.

## Wave 5 — Sheet metal (self-contained release)

Sheet metal is a subsystem, not a tool: it needs its own probes and its own
acceptance script (`scripts/acceptance_sheet_metal.py`).

- `sheet_metal_base_flange` — `InsertSheetMetalBaseFlange2`; profile sketch,
  thickness, bend radius, K-factor/bend allowance (probe defaults and pass an
  explicit `ICustomBendAllowance` so hand calcs are deterministic).
- `sheet_metal_edge_flange` — `InsertSheetMetalEdgeFlange2` on selected edges.
- `sheet_metal_miter_flange`, `sheet_metal_hem`, `sheet_metal_jog`,
  `sheet_metal_corner_trim`, `sheet_metal_break_corner`.
- `unfold_sheet_metal` / `fold_sheet_metal` — `InsertSheetMetalUnfold` /
  `InsertSheetMetalFold`.
- `list_flat_patterns` — `FeatureManager.GetFlatPatternFolder` +
  `IFlatPatternFolder`.
- `export_flat_pattern` — `IPartDoc.ExportFlatPatternView`; verified with the
  existing `verify_export` DXF checks (entities + extents).

Acceptance: L-bracket with two bends; flat-pattern DXF length = flange lengths
+ bend allowance; measured mass/volume vs analytic with the same K-factor.

## Wave 6 — Surfaces, weldments, assembly modelling (optional)

Surfaces: `surface_extrude` (`FeatureExtruRefSurface3`), `surface_revolve`
(`InsertRevolvedRefSurface`), `planar_surface` (`InsertPlanarRefSurface`),
`trim_surface` / `untrim_surface`, `thicken` (`FeatureBossThicken` /
`FeatureCutThicken`), `fill_surface` (`InsertFillSurface2`), `ruled_surface`
(`InsertRuledSurfaceFromEdge2`), `freeform` (`InsertFreeform2`). Probe the knit
entry point name. Verify surfaces by thickening to a solid and measuring volume.

Weldments: `structural_member` (`InsertStructuralWeldment5`; needs the installed
`.sldlfp` profile paths — check `ProgramData`), `trim_extend`
(`InsertWeldmentTrimFeature2`), `weld_bead` (`InsertFilletBeadFeature3`),
`weldment_cut_list` (`InsertWeldmentCutList2`). Verify by length x profile area.

Assembly modelling (small, only if wanted): `component_pattern`
(`IAssemblyDoc.InsertDerivedPattern`), `mirror_components`
(`MirrorComponents3`), `exploded_view` (`CreateExplodedView`,
`AddExplodeStep`, `ShowExploded2`).

## Suggested sequence

1. **Wave 1** — feature depth (implemented; 134-tool catalog, 26 live checks).
2. **Wave 2** — multi-body / direct editing (9 tools + body-selection helper).
3. **Wave 3** — configurations & equations (10 tools); pairs with batch/plan
   execution.
4. **Wave 4** — patterns and curves (6-9 tools).
5. **Wave 5** — sheet metal (11 tools, own acceptance suite).
6. **Wave 6** — surfaces / weldments / assembly modelling (optional).

Rough sizes: each wave is one milestone-sized chunk (~1-2 sessions with live
probing). One wave = one commit that updates the tool count in README, AGENTS.md
and CHANGELOG.md.

## Risks and mitigations

- **Hole Wizard crash** (`mfc140u.dll`, see COM-QUIRKS): one-shot spike in a
  fresh session, never a loop; the counterbore/countersink/tapped recipes are
  the shipping plan either way. Drawings hole callouts stay limited to Wizard
  holes until this works — document that dependency.
- **Silent `None` returns**: precedent (`InsertFeatureShell`, `InsertRefPlane`)
  says judge by tree diff + rebuild + mass; every new tool uses the
  `_finish_feature` fallback shape.
- **Selection marks**: reference-extrude marks are measured (profile 0,
  reference 1); combine/split/move-face remain unmeasured. Probe before tools.
- **Array marshalling**: variable-radius fillets, config parameters and
  `PostSplitBody2` take arrays; `binding.r8_array` / explicit VARIANT handling
  must be validated in the probe script first.
- **Bend allowance determinism**: do not rely on document defaults for hand
  calcs; pass explicit `ICustomBendAllowance`.
- **Cost of evidence**: per-configuration evidence means activate + rebuild.
  Batch these reads in one tool call instead of one call per configuration.
- **Version drift**: `get_capabilities` gets a `modelling` block listing which
  wave tools are live on the attached build (Wizard/rib stay guarded).

## Definition of done (per wave)

1. Probe script committed and findings folded into `docs/COM-QUIRKS.md`.
2. Typed tools registered (tier: extended unless the tool is fundamental).
3. Pure argument mapping has unit tests; COM paths are covered by live checks.
4. New live acceptance checks with hand calculations, in a standalone suite or
   named group so they can be run on demand.
5. README tool index/count, AGENTS.md traps, CHANGELOG entries updated.
6. No existing acceptance check regresses (run the full live suite on the
   milestone commit).
