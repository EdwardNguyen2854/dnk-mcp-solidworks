"""Early binding for the installed SOLIDWORKS type library.

Why this exists
---------------
On the tested build (SOLIDWORKS 2026 SP0.0), late-bound pywin32 fails in two
ways that make a pure-dynamic server unusable:

* members declared ``PROPGET`` *with arguments* are resolved on plain attribute
  access as zero-argument method objects (a bound method where a value was
  expected),
* ``IModelDoc2`` members such as ``FirstFeature`` raise
  ``DISP_E_MEMBERNOTFOUND`` because the underlying dispatch's
  ``GetTypeInfo()`` fails, so dynamic name resolution cannot work.

The fix is to generate makepy wrappers from the installed typelib and wrap
every raw dispatch in the generated interface class. Calls then go out by
``DISPID`` via ``InvokeTypes``, bypassing name resolution entirely. This is
the pattern proven by hjbaard/SolidWorks-MCP.
"""
from __future__ import annotations

import os
import subprocess
import sys

import pythoncom
import win32com.client
from win32com.client import gencache

SLDWORKS_PROGID = "SldWorks.Application"
SLDWORKS_LIBID = "{83A33D31-27C5-11CE-BFD4-00400513BB57}"

# Typelib major versions observed per release: SW2022=30 ... SW2026=34.
_KNOWN_MAJORS = tuple(range(40, 19, -1))

_module = None
_binding_info = {}


class BindingError(RuntimeError):
    """Raised when the installed typelib cannot be bound."""


def _registered_major() -> tuple[int, int] | None:
    """Find the registered typelib version by probing the registry."""
    for major in _KNOWN_MAJORS:
        try:
            tlb = pythoncom.LoadRegTypeLib(SLDWORKS_LIBID, major, 0, 0)
        except pythoncom.com_error:
            continue
        attr = tlb.GetLibAttr()
        return int(attr[3]), int(attr[4])
    return None


def _generate_from_file(tlb_path: str) -> tuple[int, int]:
    """Generate makepy wrappers straight from a .tlb file, then cache them."""
    attr = pythoncom.LoadTypeLib(tlb_path).GetLibAttr()
    major, minor = int(attr[3]), int(attr[4])
    subprocess.run(
        [sys.executable, "-m", "win32com.client.makepy", tlb_path],
        check=True,
        capture_output=True,
    )
    return major, minor


def get_module():
    """Return the generated makepy module for the installed typelib.

    Resolution order:
      1. an explicit ``SW_TYPELIB_MAJOR`` / ``SW_TYPELIB_MINOR`` override,
      2. the version registered with Windows,
      3. sibling ``sldworks.tlb`` next to ``SW_MCP_SLDWORKS_EXE``.
    """
    global _module
    if _module is not None:
        return _module

    major = os.environ.get("SW_TYPELIB_MAJOR")
    minor = os.environ.get("SW_TYPELIB_MINOR", "0")
    if major is not None:
        _module = gencache.EnsureModule(SLDWORKS_LIBID, 0, int(major), int(minor))
        _binding_info["source"] = "override"
        return _module

    registered = _registered_major()
    if registered is not None:
        _module = gencache.EnsureModule(SLDWORKS_LIBID, 0, *registered)
        _binding_info["source"] = "registry"
        return _module

    exe = os.environ.get("SW_MCP_SLDWORKS_EXE", "")
    if exe:
        tlb_path = os.path.join(os.path.dirname(exe), "sldworks.tlb")
        if os.path.exists(tlb_path):
            major, minor = _generate_from_file(tlb_path)
            _module = gencache.EnsureModule(SLDWORKS_LIBID, 0, major, minor)
            _binding_info["source"] = "file"
            return _module

    raise BindingError(
        f"could not bind typelib {SLDWORKS_LIBID}: no registered version found"
    )


def version() -> tuple[int, int]:
    """Return the (major, minor) version of the bound typelib."""
    module = get_module()
    return (int(module.MajorVersion), int(module.MinorVersion))


def wrap(obj, interface: str):
    """Wrap a raw dispatch in its generated early-bound interface class.

    ``obj`` may be a PyIDispatch or any pywin32 dispatch object. If the
    object does not support the requested interface the raw dispatch is
    returned unchanged.
    """
    module = get_module()
    cls = getattr(module, interface, None)
    if cls is None:
        raise BindingError(f"interface {interface!r} not in typelib")
    raw = getattr(obj, "_oleobj_", obj)
    try:
        qi = raw.QueryInterface(cls.CLSID, pythoncom.IID_IDispatch)
    except pythoncom.com_error:
        return obj
    return cls(qi)


def value(member):
    """Return a member's value, calling it when pywin32 exposes a method.

    Some SOLIDWORKS members are declared ``PROPGET`` with arguments; makepy
    then exposes them as bound methods even for a plain attribute access.
    Never trust ``hasattr``-style shape checks in this API; normalise here.
    """
    return member() if callable(member) else member


def r8_array(values):
    """Wrap a sequence of floats as a VT_ARRAY|VT_R8 VARIANT.

    SOLIDWORKS expects typed double arrays; a bare Python list is marshalled
    as an array of variants and is silently misread (vectors come back
    rotated or zeroed).
    """
    import win32com.client

    return win32com.client.VARIANT(
        pythoncom.VT_ARRAY | pythoncom.VT_R8, [float(item) for item in values]
    )


def call(obj, name: str, *args):
    """Get member ``name`` from ``obj`` and call it if callable."""
    member = getattr(obj, name)
    if args:
        return member(*args)
    return value(member)
