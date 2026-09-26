# Architecture

## Layers

```
MCP client
   │ stdio (default) or loopback Streamable HTTP (ToolHive)
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
    │                      drawings, drawing_iso, export, artifacts
    │                      (all run on the COM thread)
   ▼
com/binding.py ─────────── makepy wrappers + QueryInterface + value()
   │
   ▼
SOLIDWORKS COM API (metres, radians, untyped dispatches)
```

## ToolHive transport boundary

The server's normal transport is stdio. For ToolHive, the explicit
`--transport streamable-http` mode exposes the same low-level MCP server at a
loopback-only `/mcp` endpoint. The endpoint is an adapter, not a second COM
path: requests still enter `server.py`, handlers still use the same registry,
and all SOLIDWORKS calls still run on the one STA worker thread. ToolHive must
proxy the endpoint as a remote Streamable HTTP server rather than containerize
this process.

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
