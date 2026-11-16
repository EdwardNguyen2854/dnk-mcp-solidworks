---
name: dnk-solidworks-cad-house-standard
description: Editable review profile for ISO drawings, including sheet, projection, units, tolerance policy, title fields, revisions, and release status.
---

# CAD house standard

Apply this profile to a review drawing. It sets presentation defaults while functional requirements and approvals remain open.

## Review profile

| Setting | Review default |
|---|---|
| Paper | A3 landscape |
| Projection | first angle |
| Units | millimetres; two decimal places for displayed linear dimensions |
| Revision | A |
| Scale | 1:1 when the measured view outlines fit; otherwise choose a scale and record it |
| General dimensional tolerances | Do not add a blanket tolerance note until the applicable design policy is confirmed. ISO 2768-1:1989 class m remains current for general linear/angular tolerances where the specification adopts it. |
| General geometrical specification | ISO 22081:2021 is the current successor to ISO 2768-2. Apply only when the general specification and datum scheme are defined by the design authority. |
| Fits | Hole tolerance uses uppercase letters (for example H7); shaft tolerance uses lowercase letters (for example h6). Show a mating fit only when both mating parts and fit intent are specified. |
| Surface finish | No blanket Ra value. Specify finish only for identified surfaces and a confirmed process or functional requirement. |
| Title fields | Title, DrawingNumber, Revision, Material, Scale, Projection, DrawnBy, CheckedBy, ApprovedBy |
| Material, fits, datums, process, approvals | Explicitly unconfirmed until supplied by the design authority |
| Outputs | Native drawing plus review PDF; DXF only when requested |
| Status | Review drawing; not manufacturing release |

## Rules

1. Apply the profile without asking again when the user has already confirmed it in the session. State the values used in the final report.
2. Record unknown material, fit, datums, finish process, checker, and approver as unconfirmed. Do not infer them from geometry or stock properties.
3. Keep `dnk-solidworks-iso-engineering-drawing` as the procedure and this profile as the house values.
4. Use exact open-model path and configuration for every inserted view. Report the resolved reference and view-level readback; disclose when configuration readback is unavailable.
5. Keep model dimensions tied to named features and their design intent. Do not translate edge counts into feature quantities. Use drawing_audit_feature_coverage with an explicit feature-to-dimension mapping and flag uncovered critical features.
6. Review the whole sheet: frame, title block, revision table, dimensions, notes, leaders, view outlines, and keep-out zones. Estimated annotation boxes are screening evidence; inspect a raster rendering of the full sheet.
7. Hole callouts require verified native callout data. Compound cut holes and cosmetic threads are geometry-only on the current server and must not be presented as Hole Wizard callouts.
8. Do not call a drawing released until required functional tolerances, material/process requirements, datum scheme, title-block approvals, and human review are complete.
