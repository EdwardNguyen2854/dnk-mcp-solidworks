# Product Vision

## Purpose

This project helps an AI agent work with real, editable mechanical CAD documents alongside a human engineer. It addresses the gap between an agent's ability to describe a design and its ability to create, inspect, revise, and hand off that design in a native CAD workspace.

CAD work is stateful and detail-sensitive. An operation can appear to succeed while producing the wrong geometry, the wrong drawing, or no useful change at all. A useful agent therefore needs more than a way to issue commands: it needs a bounded way to understand the current document, make deliberate changes, inspect the result, and communicate what it could and could not verify.

The product's value is reliable, reviewable engineering work—not the number of available operations and not autonomous design for its own sake.

## Target users and use cases

### Primary users

- Mechanical engineers and designers who want an AI agent to help create or revise parts, assemblies, and engineering drawings.
- Engineering automation practitioners who need repeatable agent workflows over real CAD documents.
- AI agents acting on a user's behalf, within the capabilities and constraints made available by the product.

### Key use cases

- Turn a sufficiently specified mechanical concept into an editable parametric part, then refine it through an inspect-and-correct loop.
- Inspect an existing model's features, geometry, dimensions, and mass properties to answer engineering questions or identify issues.
- Assemble existing components, position them, apply relationships, and check for interference.
- Create or update a drawing from a model, add and organize relevant views and annotations, and check observable drawing state before handoff.
- Save or export a deliverable and verify that the resulting artifact is present and structurally readable.
- Recover from risky changes using checkpoints, or stop with a clear explanation when the requested operation is unsupported or cannot be verified.

## Product vision and principles

The product should become a dependable agent interface for mechanical CAD work: capable enough to complete meaningful design workflows, cautious about what it claims, and understandable to the engineer reviewing its work.

1. **Evidence over assertion.** A completed operation is not proof of a correct result. Report observable changes and measurements, and distinguish verified facts from assumptions or unverified outcomes.
2. **Editable engineering artifacts.** Prefer changes that preserve a useful, understandable design history and native document state over opaque outputs that are difficult to revise.
3. **Explicit intent and references.** Make units, selected geometry, source models, configurations, and other consequential references clear. Do not silently guess when ambiguity could change the design.
4. **Fail visibly and recoverably.** Unsupported, unsafe, or failed operations should produce an actionable explanation. Risky work should have a practical recovery path.
5. **Capability honesty.** Expose what is actually available in the current CAD session and version. Do not imply universal support or standards compliance from a partial check.
6. **Human engineering judgment remains essential.** The agent can perform bounded operations and gather evidence; it cannot invent functional requirements, approve a design, or replace engineering review.
7. **Workflow quality over tool count.** Add capability when it improves a complete, verifiable user workflow, not merely to expand a catalog.

## Main features and workflows

The product's core capability areas are:

- **Session and document work:** understand the active CAD context, discover available capabilities, and open, create, save, or close documents through explicit operations.
- **Parametric part modeling:** create and edit sketches and features, apply dimensions and relationships, and make common geometry changes while retaining editable model intent.
- **Model inspection and verification:** inspect model structure and geometry; measure properties such as volume, bounds, and distances; check rebuild or model issues; and compare a result against caller-supplied tolerances when appropriate.
- **Assembly work:** insert and position components, manage supported relationships, inspect assembly state, and detect geometric interference.
- **Engineering drawings:** create and manage sheets and views, add dimensions and annotations, inspect drawing state and feature coverage, and check observable layout and release conditions.
- **Transactions and deliverables:** create and use recovery checkpoints, save documents, export common deliverables, and verify observable properties of exported files.

### Reference workflow

1. The user describes the goal, constraints, source documents, and any design intent that must not be guessed.
2. The agent checks the live document and available capabilities, then identifies missing information or consequential assumptions.
3. The agent performs bounded modeling, assembly, or drawing operations, preserving opportunities to inspect and recover.
4. The product reports the changed state and relevant measurements, issues, and limitations.
5. The agent compares the result with the stated goal and tolerances, corrects clear discrepancies, or asks the user to resolve an engineering decision.
6. The user reviews the native document and evidence, then decides whether to save, export, approve, or continue iterating.

This describes the intended collaboration flow, not a required interface or system design.

## High-level system direction

The product should remain an agent-facing capability layer for working with a live CAD workspace, rather than becoming a replacement CAD application or a general-purpose code execution environment. Its role is to make useful CAD actions discoverable and constrained, and to close the loop with inspection, evidence, and recovery.

The CAD document remains the source of truth for model and drawing state. The agent should be able to move between understanding the document, making a bounded change, inspecting the result, and explaining the outcome. The product should separate what the CAD system reports from what has actually been verified, and should surface capability or version limitations where they affect a workflow.

The current product is centered on SOLIDWORKS and an MCP-compatible agent-tool integration. These are current product boundaries and integration points; this vision does not prescribe the connection mechanism, internal architecture, implementation stack, or future platform strategy.

## Key integrations and dependencies

- **CAD workspace:** Current scope depends on an available, installed, licensed SOLIDWORKS environment and a user-accessible session. Supported operations depend on the session's actual capabilities and release.
- **AI agent client:** An agent client must be able to discover and call the product's bounded CAD capabilities and receive structured outcomes. The product should not depend on a particular agent brand.
- **MCP integration:** The current product is delivered through an MCP-compatible tool interface. This is an integration contract, not a commitment to a particular internal design.
- **Engineering inputs:** Source models, drawings, templates, configuration data, and any required company or project conventions may be necessary for specific workflows. Their presence and suitability must not be assumed.
- **Human review:** Functional requirements, tolerances, material and process choices, standards interpretation, and release approval may require decisions from a qualified person.

## UX and human–AI collaboration model

The intended experience is conversational and iterative, with the agent translating user intent into visible changes in the user's CAD work—not hiding those changes behind an opaque generation step.

- The agent should first understand the current document and capability limits rather than assume a blank or idealized state.
- Requests and results should use clear, consistent units and identify the geometry or document references involved.
- Routine, bounded modeling actions may proceed without interrupting the user at every step, provided the user can inspect the outcome and recover from risky changes.
- Consequential choices—such as unspecified functional intent, fits, tolerances, material, manufacturing requirements, or release decisions—belong to the human unless explicitly provided by the user.
- Saving, overwriting, discarding unsaved work, and release approval should remain explicit user-controlled decisions.
- The agent should show evidence relevant to the task, state uncertainty and unsupported coverage plainly, and avoid presenting a clean rebuild or a successful export as proof of engineering fitness.
- Visual review of a model or drawing remains part of the workflow where appearance, layout, symbols, or annotations cannot be fully assessed from structured checks alone.

## Constraints, assumptions, and non-goals

### Constraints

- The current product operates on a live SOLIDWORKS session; it is not intended to launch the CAD application or replace the native CAD environment.
- CAD behavior and available operations vary by release. Capabilities must be discovered or validated rather than assumed to be identical everywhere.
- The product can verify observable document and geometry properties, but not every aspect of engineering meaning or visual correctness.
- The product must keep operations bounded to CAD and document workflows. Arbitrary code execution is outside the product's role.
- Written standards, company practices, templates, and functional intent may be incomplete or unavailable; the product must not claim compliance or approval without adequate evidence and authority.

### Important assumptions

- **Assumption — primary domain:** The primary users work on mechanical parts, assemblies, and drawings, rather than general-purpose 3D art or unrelated document types.
- **Assumption — collaboration:** A human engineer remains available to supply missing intent and review consequential outcomes, even when routine operations are agent-driven.
- **Assumption — current CAD target:** SOLIDWORKS remains the supported CAD product for the current scope. No other CAD application is implied to be supported.
- **Assumption — evidence has limits:** Measurements, read-back, and visual inspection increase confidence but do not establish fitness for manufacture, safety, or regulatory compliance by themselves.

### Non-goals

- Replacing SOLIDWORKS or serving as a standalone CAD editor.
- Designing a part from underspecified requirements and claiming it is functionally correct.
- Making unsupervised engineering, safety, manufacturing, standards, or release decisions.
- Guaranteeing that every CAD operation, feature type, file format, or release is supported.
- Treating the number of tools or breadth of an API surface as the primary measure of product quality.
- Prescribing a specific implementation architecture, technology stack, database, vendor ecosystem, or platform strategy.

## MVP scope and future roadmap

### MVP: a trustworthy end-to-end loop

The MVP is the smallest product that can take a meaningful mechanical task from an existing CAD context to a reviewable result. It should include:

- Discovery of the active session, document context, and available operations.
- Core editable part-modeling workflows and useful model inspection.
- A practical path through common assembly and engineering-drawing tasks.
- Verification after changes, with measured evidence and clear failure reporting.
- Checkpoint and recovery support for risky work.
- Saving and exporting deliverables with basic artifact verification.
- A human review and decision boundary for ambiguous intent and release-critical work.

This scope is about completing a coherent workflow, not claiming exhaustive CAD coverage or fully automated design-to-release.

### Future direction (candidate areas, not commitments)

- Deepen part-modeling coverage, including multi-body editing and more expressive parametric families.
- Support repeatable multi-step plans where the agent can explain the intended sequence, monitor progress, and stop safely when assumptions fail.
- Extend specialized mechanical workflows—such as sheet metal, surfaces, and weldments—only when their capabilities can be validated to an appropriate standard.
- Improve semantic drawing checks, including explicit mapping between design-critical features and drawing coverage, while keeping human review for intent and visual quality.
- Strengthen compatibility reporting and workflow verification across supported CAD releases.

Priority should follow validated user value, reliability, and the availability of meaningful acceptance checks. These candidates do not establish a delivery schedule or guarantee future support.

## Success criteria

The product is succeeding when:

- Users can complete useful part, assembly, and drawing workflows in their native CAD context with less repetitive manual interaction.
- Changes produce editable documents that match explicit user goals and caller-specified tolerances, as demonstrated by relevant measurements or other observable evidence.
- The agent can distinguish verified success, partial success, failure, and uncertainty—and give the user a useful next step in each case.
- Unsupported or version-sensitive operations are surfaced before they silently undermine the result.
- Users can recover from risky changes and retain control over saving, discarding, and approving deliverables.
- Drawing and export checks catch observable omissions and defects without being misrepresented as complete engineering or standards approval.
- Confidence grows through real end-to-end acceptance evidence, not solely through successful API calls or an expanding tool catalog.

Success should be assessed per workflow and supported CAD release. Numerical performance targets should be set only after collecting a trustworthy baseline from representative engineering tasks.
