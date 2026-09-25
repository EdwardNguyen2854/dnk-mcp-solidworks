# Architecture

## Layers

```
MCP client
   │ stdio (JSON-RPC)
   ▼
server.py ──────────────── list_tools (tier-filtered), call_tool
   │ asyncio.to_thread
   ▼
registry.py ────────────── ToolSpec catalog, schema validation, envelope
   │ handler(args)
   ▼
tools/{core,extended,advanced,debug}.py
   │ run(domain_fn)
   ▼
com/worker.py ──────────── one dedicated STA thread; every COM call is queued
   │ job()
   ▼
domain/* ───────────────── documents, sketch, features, inspect, assemblies,
   │                      drawings, export  (all run on the COM thread)
   ▼
com/binding.py ─────────── makepy wrappers + QueryInterface + value()
   │
   ▼
SOLIDWORKS COM API (metres, radians, untyped dispatches)
```

## Why a dedicated COM thread

COM is apartment-threaded and thread-affine; the MCP server is asyncio. All
SOLIDWORKS work is posted to a single background thread, so the "one COM
session, one thread" rule holds by construction. The worker also owns the
per-call timeout: if SOLIDWORKS stops answering (usually a modal dialog), the
worker is marked blocked and further calls fail fast with a clear hint instead
of hanging the agent.

## Why early binding with interface wrapping

On the tested build, late-bound name resolution fails for `IModelDoc2`
members, and `NewDocument`/`ActiveDoc` return untyped dispatches. Every
dispatch that crosses the boundary is QueryInterfaced to its generated
interface class and invoked by DISPID. See
[ADR 0001](adr/0001-binding-strategy.md) and [COM quirks](COM-QUIRKS.md).

## The result envelope

```
{ "ok": true,
  "data": {...},
  "evidence": { "rebuild": {...}, "mass_properties": {...}, "bounding_box": {...} },
  "warnings": [...] }
```

or

```
{ "ok": false,
  "error": { "code": "...", "message": "...", "hint": "...", "recoverable": true } }
```

Handlers raise typed `SwMcpError` subclasses; the server converts them at the
boundary so no raw COM exception ever reaches the client. Image results are
returned as MCP image content alongside the JSON envelope.

## Units and selection

- Tool parameters are millimetres and degrees; conversion happens once in
  `com/units.py`.
- Topology indices come from `list_faces` / `list_edges` /
  `list_sketch_segments` and are resolved back to `IEntity.Select4` calls
  with marks. Index snapshots are invalidated by geometry changes, so tools
  re-list before selecting.

## Transactions

`tx/checkpoint.py` snapshots the active document (file copy, or save-a-copy
for unsaved documents) into `%LOCALAPPDATA%\MCP-Solidworks\checkpoints`,
debounced by `SW_MCP_CHECKPOINT_DEBOUNCE_SEC`. `rollback_to_checkpoint`
closes without saving and reopens a snapshot.
