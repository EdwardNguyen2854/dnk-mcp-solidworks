# Contributing to dnk-mcp-solidworks

Thanks for wanting to improve the project. This repository drives a live COM
application, so correctness matters more than speed. Please read this file and
[`AGENTS.md`](AGENTS.md) before changing code.

## Code of conduct

By participating you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Ways to contribute

- **Bug reports** — use the bug issue template and include your SOLIDWORKS
  version, typelib version (`get_capabilities`), Python version, and the exact
  tool call and result envelope.
- **Feature requests** — describe the engineering workflow, not only the API
  call you have in mind.
- **Documentation** — corrections to `docs/COM-QUIRKS.md` are especially
  valuable, because that file records measured behavior.
- **Code** — bug fixes and new tools that follow the existing typed surface.

## Development setup

```powershell
git clone https://github.com/EdwardNguyen2854/dnk-mcp-solidworks.git
cd dnk-mcp-solidworks
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Unit tests do not need SOLIDWORKS:

```powershell
python -m pytest tests/unit -q
```

Live acceptance suites need SOLIDWORKS **installed, licensed, and running**.
They attach to your session and create/close their own documents, discarding
them without saving, but **save your work first** in case SOLIDWORKS crashes:

```powershell
python scripts/mcp_smoke.py
python scripts/acceptance.py
python scripts/acceptance_asm_drw.py
```

## Architecture rules (non-negotiable)

These come from [`AGENTS.md`](AGENTS.md) and exist because violating them
silently corrupts geometry or crashes SOLIDWORKS:

- All COM access runs on the single STA worker thread via `com/worker.run(fn)`.
- Wrap every raw dispatch with `binding.wrap(obj, "IModelDoc2")`.
- Pass plain ints for out parameters; unpack with `session.com_result`.
- Normalise propget-with-args members with `binding.value(...)`.
- Use `binding.r8_array(...)` for typed double arrays.
- Tool arguments are `_mm` / `_deg`; convert only in `com/units.py`.
- Never trust feature return values. Judge success by rebuild +
  `GetWhatsWrong` + measured mass properties.
- Mutations must return an `evidence` payload; failures raise an `SwMcpError`
  subclass.
- Probe the installed typelib with `scripts/probe_api.py` before coding against
  an API call whose published documentation disagrees with the shipped build.
- Keep `README.md`, `AGENTS.md`, the docs, and the bundled skills in sync when
  behavior changes.

## Pull request checklist

1. Branch from `main` with a descriptive name.
2. Add or update unit tests for logic that does not need SOLIDWORKS.
3. Run `python -m pytest tests/unit -q` and make it green.
4. If you touched COM behavior, run the relevant live suite and paste the
   measured result (checks passed) into the PR description.
5. Update `CHANGELOG.md` under `[Unreleased]`.
6. Keep the diff focused; do not mix formatting-only changes with behavior.
7. Confirm you have the right to submit the code and that it does not copy
   code from a project with an incompatible license.

## License of contributions

This project is licensed under the Apache License 2.0. Unless you explicitly
state otherwise, any contribution you intentionally submit for inclusion in the
project is licensed under the same terms, as described in Section 5 of the
license.

## Attribution

If you publish a fork or derivative work, keep `LICENSE` and `NOTICE` and credit
**Edward Nguyen** and the original repository, as described in
[`NOTICE`](NOTICE).
