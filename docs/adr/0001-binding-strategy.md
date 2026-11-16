# ADR 0001: Early binding via makepy + interface wrapping

- Status: Accepted
- Date: 2026-09-25
- Verified on: SOLIDWORKS 2026 SP0.0, typelib version 34.0, Python 3.12, pywin32 309

## Context

The server drives a running SOLIDWORKS session through its COM API. pywin32
can talk to COM in two ways:

1. **Late binding** (`win32com.client.Dispatch` / `dynamic.Dispatch`): name
   resolution at call time through `IDispatch.GetIDsOfNames`.
2. **Early binding** (makepy-generated wrappers + `InvokeTypes`): calls go by
   `DISPID` directly from the generated module.

The public reference servers disagree. Slacker-LLC ships late binding and
compensates with `_FlagAsMethod` patches and "return values lie" workarounds.
hjbaard documents that early binding is *mandatory* on the build they tested
because late binding fails outright.

## Findings on SOLIDWORKS 2026 SP0.0 (measured)

- `gencache.EnsureModule(LIBID, 0, 0, 0)` fails with `Library not registered`
  even though `pythoncom.LoadRegTypeLib(LIBID, 34, 0, 0)` succeeds. Version
  probing is required.
- `NewDocument` and `ActiveDoc` return **untyped `CDispatch`** objects even
  from an early-bound `ISldWorks` instance (the typelib declares the return
  as bare `IDispatch`).
- Calling `FirstFeature` on that dynamic dispatch raises
  `DISP_E_MEMBERNOTFOUND` (`Member not found`), because `GetTypeInfo()` fails
  on the returned dispatch.
- Wrapping the raw `PyIDispatch` with
  `raw.QueryInterface(IModelDoc2.CLSID, IID_IDispatch)` and then constructing
  the generated interface class makes `FirstFeature`, `GetTitle`, and other
  members work through `InvokeTypes`.
- Members declared `PROPGET` *with arguments* appear as bound methods on plain
  attribute access (for example `app.RevisionNumber` is a method, not a
  string). Every access goes through a `value()` normaliser.

## Decision

Use early binding as the default and only strategy:

- `com/binding.py` locates the registered typelib version by probing majors
  40..20 (SW2026 is 34), with `SW_TYPELIB_MAJOR`/`SW_TYPELIB_MINOR` overrides
  and a `.tlb`-file fallback via `SW_MCP_SLDWORKS_EXE`.
- Every dispatch that crosses the boundary is normalised with
  `binding.wrap(obj, "IInterface")` (QueryInterface + generated class).
- A generic `binding.value()` treats callables as zero-argument property
  getters. Tools never rely on attribute shape.

## Consequences

- `IModelDoc2` and friends expose all ~800 members with correct by-ref
  signatures; no hand-maintained `_FlagAsMethod` list is needed.
- The generated module (~6 MB of Python) is cached by pywin32 under `gen_py`;
  first start does the generation once.
- Interface names must exist in the typelib; `binding.wrap` fails loudly if
  not, which is the desired behaviour for a version-guarded server.
- The spike proves the full path: attach -> part -> sketch -> extrude ->
  measured volume 3.0e-05 m3 with a 1.1e-14% error against hand calculation.
