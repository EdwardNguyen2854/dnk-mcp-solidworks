# CADGenBench: fit for SOLIDWORKS MCP evaluation

**Research date:** 2026-09-27. Sources are upstream CADGenBench repository files; links below point to `huggingface/cadgenbench` on `main`.

## Findings

- **Tasks and inputs.** CADGenBench has two task types: `generation` (engineering drawing to 3D part) and `editing` (existing STEP plus requested change). Sample `description.yaml` declares the task type; editing also supplies `input.step`. The public input dataset is `HuggingAI4Engineering/cadgenbench-data`; ground truth is in a separate private dataset, so local users should not assume access to reference solids. [README](https://github.com/huggingface/cadgenbench/blob/main/README.md) · [submission contract](https://github.com/huggingface/cadgenbench/blob/main/docs/benchmark/submission.md)
- **Artifact contract.** Produce one `output.step` (or `.stp`) per sample. The grader checks a valid, watertight B-rep meshing to a closed manifold; it rigidly aligns candidates to ground truth (no scaling). Canonical pose is recommended, not mandatory. Submission is a ZIP containing per-sample folders and root `meta.json`; the Space evaluates and publishes results. [Submission contract](https://github.com/huggingface/cadgenbench/blob/main/docs/benchmark/submission.md) · [README](https://github.com/huggingface/cadgenbench/blob/main/README.md)
- **Scoring.** Validity is a hard gate. Generation score weights shape similarity/interface/topology as 0.4/0.4/0.2; editing renormalizes shape against unchanged input and uses 0.6/0.3/0.1. Shape compares surface and volume, interface checks authored mating keep-in/keep-out volumes, and topology compares Betti numbers. [Metrics](https://github.com/huggingface/cadgenbench/blob/main/docs/metrics.md)
- **Licensing and dependencies.** Repository declares Apache-2.0 and Python >=3.12. Core dependencies include build123d, trimesh, manifold3d, NumPy, SciPy, Open3D, Pillow, PyYAML, PyVista and huggingface_hub. The optional baseline adds LiteLLM and python-dotenv; CadQuery is an optional backend extra. Participation does not require installing the scoring repository. [LICENSE](https://github.com/huggingface/cadgenbench/blob/main/LICENSE) · [pyproject.toml](https://github.com/huggingface/cadgenbench/blob/main/pyproject.toml) · [README](https://github.com/huggingface/cadgenbench/blob/main/README.md)

## Applicability to this SOLIDWORKS MCP server

**Useful as an artifact-level benchmark, not a turnkey MCP test harness.** The upstream contract is CAD-tool agnostic and only requires STEP candidates, so a workflow can invoke this server's tools over stdio against a running SOLIDWORKS session, save/export each resulting model as STEP, and place it in the prescribed sample folder. The scoring pipeline can then judge geometry independently of the CAD authoring interface.

The repository context here says the server is Windows-only, attaches to an already-running SOLIDWORKS instance over COM, uses stdio MCP calls, and has live acceptance scripts. This makes a local runner plausible on the Windows/SOLIDWORKS machine, but not a normal unattended cross-platform benchmark job: it needs a live interactive CAD process and the upstream scoring stack has its own Python 3.12/geometry dependencies. Existing acceptance scripts verify known hand-calculated geometry and are complementary; CADGenBench would add diverse drawing-driven and edit-request cases with geometric scoring.

Important boundaries: the benchmark does **not** prescribe MCP calls, expose ground truth publicly, or test the feature tree, editability, tool protocol, or whether native SOLIDWORKS files are saved correctly. Its deliverable is STEP geometry only. Editing can be exercised by opening the provided `input.step`, applying the requested change through MCP, and exporting `output.step`; generation requires translating drawing/description inputs into a tool sequence. Results should be treated as candidate geometry scores, not acceptance evidence for every server capability.

## Suggested evaluation shape

1. Select public samples and define a repeatable prompt/tool-call procedure for each task type.
2. Run it only with SOLIDWORKS already open; export each final solid to the exact sample `output.step` path.
3. Run the upstream local validity check where available, then package and submit to the Space for full scoring (which compares against private ground truth).
4. Record MCP/tool failures separately from CADGenBench scores; retain per-sample `result.json`/run summary as geometric evidence.

## Local runner in this repository

`scripts/cadgenbench_runner.py` runs prepared **generation** cases through the
MCP stdio server. SOLIDWORKS must already be running. It never downloads data
or submits a score. Prepare a JSON manifest with explicit tool calls, for
example:

```json
{
  "cases": [
    {
      "id": "sample-001",
      "calls": [
        {"tool": "create_sketch", "args": {"plane": "front"}},
        {"tool": "sketch_rectangle", "args": {"x1_mm": 0, "y1_mm": 0, "x2_mm": 40, "y2_mm": 30}},
        {"tool": "exit_sketch", "args": {}},
        {"tool": "boss_extrude", "args": {"depth_mm": 10}}
      ]
    }
  ]
}
```

Run it with `python scripts/cadgenbench_runner.py cases.json`. Each case gets a
fresh part document; the runner exports `sample-001/output.step`, calls
`verify_export`, closes the document without saving, and writes
`artifacts/cadgenbench/run-results.json`. Tool sequences are deliberately
explicit (this is not an LLM agent); generation from benchmark drawings and
STEP editing need task-specific adapters. Local verification is not the
private-ground-truth CADGenBench score or a submission ZIP.

No application code was changed as part of the initial research.
