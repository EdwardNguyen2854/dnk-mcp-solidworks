---
name: cad-remodel
description: Re-model a SOLIDWORKS part while preserving the source, comparing geometry and editable design data, and holding release when functional intent is unknown.
---

# CAD remodel

Use when rebuilding or substantially restructuring a SOLIDWORKS model. The remodel is a separate deliverable; keep the source model available as the comparison reference.

## Workflow

1. Record the exact source path, active configuration, feature tree, rebuild/What's Wrong state, material assignment, mass properties, exact extrema, topology, and screenshot. Do not modify or save over the source.
2. Save a separate working copy or create a new target model at a distinct path. Confirm its path/configuration before any drawing references it.
3. Rebuild editable features from known dimensions and constraints. Preserve meaningful sketches, design parameters, named features, and configuration intent. Mark inferred dimensions or unknown functional requirements for review.
4. Diagnose sketches with list_sketches: report SOLIDWORKS constraint status and the model-to-sketch transform. Degrees of freedom remain unknown when the installed ISketch typelib does not expose a supported accessor; never estimate them from entity counts.
5. Inspect feature parameters with inspect_editable_features; only API-probed definition families have editable values reported. Treat unsupported feature data as unavailable.
6. Compare the target against the source with compare_model_geometry, providing explicit volume, exact-extrema, and sampled surface tolerances chosen for the intended use. Read topology as evidence. The surface metric samples tessellated vertices/triangles and is not an analytic Hausdorff proof.
7. Review discrepancies and compare feature names, sketch constraints/transforms, editable parameter readback, configurations, and source/target screenshots. A geometry pass does not prove design intent or functional equivalence.
8. Save/reopen the target and repeat rebuild, geometry comparison, and editable-parameter checks. Confirm the original source remains unchanged and separate.
9. Hold release when material, functional dimensions/fits, datums, process/finish, or approval fields are unknown. Report the remodel as a review model with explicit open items.
