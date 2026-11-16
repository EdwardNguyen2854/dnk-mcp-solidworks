# Security policy

## Supported versions

Only the latest release on `main` is supported with security fixes.

| Version | Supported |
|---|---|
| 0.5.x | Yes |
| < 0.5 | No |

## Reporting a vulnerability

Please **do not open a public issue** for a security problem. Report it
privately through GitHub's [Security Advisories](https://github.com/EdwardNguyen2854/dnk-mcp-solidworks/security/advisories/new)
feature. Include:

- affected version and commit;
- SOLIDWORKS version and typelib version;
- steps to reproduce;
- impact (for example, unexpected file writes, path escape, secret exposure);
- any suggested fix.

You can expect an acknowledgement within a few days. Please give a reasonable
window to release a fix before public disclosure.

## Threat model and scope

This server is a local Windows process that controls a live SOLIDWORKS session
over COM. It is designed for a trusted local operator and a trusted MCP client.

In scope:

- **Path sandbox escape.** Writes must stay under `SW_MCP_OUTPUT_ROOT` and
  `SW_MCP_ALLOWED_ROOTS`. Reads of existing files are intentionally allowed
  anywhere, so a path-traversal report about reads is only a vulnerability if it
  becomes a write, an execution, or an information leak to a remote party.
- **Arbitrary COM execution.** The tool surface is typed and fixed. A way to
  invoke arbitrary COM or Python through a tool argument is a vulnerability.
- **Network exposure.** The default transport is stdio. The optional
  Streamable HTTP transport must remain loopback-only by default; a way to bind
  it to a non-loopback interface without explicit user action is a
  vulnerability.
- **Secret or model-data leakage.** Logs and tool envelopes must not contain
  image base64, credentials, or absolute paths that are not needed.
- **Denial of service of the user's session.** A tool call that hangs, crashes,
  or corrupts a SOLIDWORKS document without an explicit warning is a
  reliability bug; report it as a security issue if it can cause data loss.

Out of scope:

- SOLIDWORKS itself, its licensing, and Dassault Systèmes' own vulnerabilities.
- Damage caused by running live acceptance suites without saving work.
- Vulnerabilities that require an already-compromised local machine or an
  attacker who can edit the server's own source or environment.

## Safe defaults

- No network access in the server itself.
- Writes are sandboxed to the output root and explicitly allowed roots.
- Operations are checkpointed and verified.
- The HTTP adapter binds to `127.0.0.1` by default and has no authentication;
  never expose it to an untrusted network.
