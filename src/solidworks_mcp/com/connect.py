"""Attach to a running SOLIDWORKS session.

The server never launches SOLIDWORKS. Attaching to the user's live session is
the safety property that makes this tool usable: if a tool cannot do something,
neither could a macro in the document the user is looking at.
"""
from __future__ import annotations

import win32com.client

from . import binding


class SolidworksNotRunning(RuntimeError):
    """No running SOLIDWORKS instance was found."""


def attach():
    """Attach to the running SOLIDWORKS instance with early binding."""
    binding.get_module()
    try:
        app = win32com.client.GetActiveObject(binding.SLDWORKS_PROGID)
    except Exception as exc:
        raise SolidworksNotRunning(
            "no running SOLIDWORKS instance found; start SOLIDWORKS first"
        ) from exc
    if app is None:
        raise SolidworksNotRunning("SOLIDWORKS returned an empty application object")
    return app


def revision(app) -> str:
    return str(binding.value(app.RevisionNumber))
