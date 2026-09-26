# Third-party notices

This project is a clean-room implementation. It was designed by studying the
following open-source projects and adopts their documented patterns and
lessons; no source code was copied verbatim. Attribution is kept here because
the ideas are theirs. See `docs/PRIOR-ART.md` for the adopted/unmined ledger
and the tool-surface diff against these projects.

| Project | License | What was learned |
|---|---|---|
| [Slacker-LLC/solidworks-mcp](https://github.com/Slacker-LLC/solidworks-mcp) | Apache-2.0 | Declarative selection, explicit units, screenshots as image content, the COM quirk playbook (flagged propget methods, modal dimension dialog, return values that lie, reference-plane marks, `through_all_both` handling), plus the verified sketch-editing calls, draft/sweep/loft ("blend") argument lists and marks, `SimpleHole2` SelectData placement, and component selection via `GetSelectByIDString` |
| [hjbaard/SolidWorks-MCP](https://github.com/hjbaard/SolidWorks-MCP) | MIT | Closed-loop verification (measured mass properties on every mutation), fail-loud errors, mandatory early binding with interface wrapping, dedicated STA COM worker thread |
| [czuryk/SolidworksMCP](https://github.com/czuryk/SolidworksMCP) | MIT | Transactions, checkpoints and rollback, invariants, idempotency, budgets, capability discovery, version guards |
| [jaylamping/solidworks-mcp](https://github.com/jaylamping/solidworks-mcp) | MIT | Tool tiers, debounced auto-checkpoints, allowed-roots sandboxing, confirmation gates, generated tool catalogs and schema checks |
| [just1step/solidworks-mcp](https://github.com/just1step/solidworks-mcp) | MIT | One process owns the COM/STA session; stdio proxy for clients; version support matrices |
| [alisamsam/Solidworks-MCP](https://github.com/alisamsam/Solidworks-MCP) | MIT | Minimal tool baseline, registry-based installation discovery, unit conversion, version-aware API fallbacks |

SOLIDWORKS is a trademark of Dassault Systèmes. This project is not affiliated
with or endorsed by Dassault Systèmes.
