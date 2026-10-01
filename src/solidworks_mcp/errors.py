"""Error taxonomy and the tool result envelope.

Every tool returns the same shape:

    {"ok": true, "data": {...}, "evidence": {...}, "warnings": [...]}

or

    {"ok": false, "error": {"code", "message", "hint", "recoverable"}}

Handlers raise :class:`SwMcpError` subclasses; the server converts them at the
boundary so no COM exception ever reaches the MCP client raw.
"""
from __future__ import annotations

from typing import Any


class SwMcpError(RuntimeError):
    code = "INTERNAL"
    recoverable = False
    hint: str | None = None

    def __init__(
        self,
        message: str,
        *,
        hint: str | None = None,
        recoverable: bool | None = None,
        **details: Any,
    ) -> None:
        super().__init__(message)
        self.message = message
        if hint is not None:
            self.hint = hint
        if recoverable is not None:
            self.recoverable = recoverable
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "code": self.code,
            "message": self.message,
            "hint": self.hint,
            "recoverable": self.recoverable,
        }
        if self.details:
            payload["details"] = self.details
        return payload


class SolidworksNotRunningError(SwMcpError):
    code = "SW_NOT_RUNNING"
    recoverable = True
    hint = "Start SOLIDWORKS, then retry."


class NoActiveDocumentError(SwMcpError):
    code = "NO_ACTIVE_DOCUMENT"
    recoverable = True
    hint = "Create or open a document first."


class WrongDocumentTypeError(SwMcpError):
    code = "WRONG_DOCUMENT_TYPE"
    recoverable = True


class InvalidParameterError(SwMcpError):
    code = "INVALID_PARAMETER"


class PathNotAllowedError(SwMcpError):
    code = "PATH_NOT_ALLOWED"
    hint = "Use a path under the configured allowed roots."


class PathNotFoundError(SwMcpError):
    code = "PATH_NOT_FOUND"


class SelectionError(SwMcpError):
    code = "SELECTION_INVALID"
    recoverable = True


class ReferenceNotFoundError(SwMcpError):
    code = "REFERENCE_NOT_FOUND"
    recoverable = True
    hint = "Ask the engineer to re-select the entity."


class ReferenceAmbiguousError(SwMcpError):
    code = "REFERENCE_AMBIGUOUS"
    recoverable = True
    hint = "The reference cannot be resolved to one entity; re-select it."


class ReferenceDocumentMismatchError(SwMcpError):
    code = "REFERENCE_DOCUMENT_MISMATCH"
    recoverable = True
    hint = "Activate the document the reference was captured in."


class FeatureBuildError(SwMcpError):
    code = "FEATURE_FAILED"
    recoverable = True


class ModalDialogError(SwMcpError):
    code = "MODAL_DIALOG"
    recoverable = True
    hint = "Dismiss the dialog in SOLIDWORKS, then retry."


class ComCallError(SwMcpError):
    code = "COM_ERROR"
    recoverable = True


class OperationTimeoutError(SwMcpError):
    code = "TIMEOUT"
    recoverable = True
    hint = (
        "SOLIDWORKS may be blocked by a modal dialog. Dismiss any dialog, "
        "then retry."
    )


class WorkerBlockedError(SwMcpError):
    code = "WORKER_BLOCKED"
    recoverable = False
    hint = "Restart the MCP server after dismissing the dialog."


class VerificationError(SwMcpError):
    code = "VERIFICATION_FAILED"
    recoverable = True


class NotImplementedToolError(SwMcpError):
    code = "NOT_IMPLEMENTED"


def ok(
    data: dict[str, Any] | None = None,
    *,
    evidence: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
    images: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"ok": True}
    if data is not None:
        payload["data"] = data
    if evidence is not None:
        payload["evidence"] = evidence
    if warnings:
        payload["warnings"] = warnings
    if images:
        payload["_images"] = images
    return payload


def fail(error: SwMcpError) -> dict[str, Any]:
    return {"ok": False, "error": error.to_dict()}


def translate_com_error(exc: Exception, context: str) -> SwMcpError:
    """Convert a pywin32 com_error into a typed server error."""
    args = getattr(exc, "args", ())
    hresult = args[0] if args else None
    text = args[2] if len(args) > 2 and args[2] else str(exc)
    if hresult == -2147417846:  # RPC_E_SERVERCALL_RETRYLATER / busy
        return ComCallError(
            f"{context}: SOLIDWORKS is busy",
            hresult=hresult,
            recoverable=True,
            hint="A command may be active; retry in a moment.",
        )
    return ComCallError(f"{context}: {text}", hresult=hresult)
