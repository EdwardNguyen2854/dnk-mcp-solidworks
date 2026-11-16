## Summary

<!-- What changed, and why. Link the issue if one exists. -->

Fixes #

## Type of change

- [ ] Bug fix
- [ ] New tool / capability
- [ ] Documentation
- [ ] Refactor (no behavior change)
- [ ] Test / CI
- [ ] Breaking change

## Verification

- [ ] `python -m pytest tests/unit -q` passes
- [ ] Relevant live acceptance suite run against a running SOLIDWORKS session
- [ ] New/changed COM behavior recorded in `docs/COM-QUIRKS.md`
- [ ] `README.md`, `AGENTS.md`, and bundled skills updated if behavior or
      tool counts changed
- [ ] `CHANGELOG.md` updated under `[Unreleased]`

## Live acceptance evidence

<!-- Paste the suite name and the measured checks. Skip if not applicable. -->

```
scripts/...: N/N passed
```

## Risk and rollback

<!-- What can this break? Can a user recover a document? Does it touch the
COM worker, binding, units, or selection? -->

## License

- [ ] I have the right to submit this code and it is licensed under
      Apache-2.0.
- [ ] I did not copy code from a project with an incompatible license.
