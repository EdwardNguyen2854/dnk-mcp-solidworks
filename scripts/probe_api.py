#!/usr/bin/env python
"""Probe the installed SOLIDWORKS type libraries.

The published API reference disagrees with the shipped type library often
enough to matter (argument counts, enum values), so every signature this
server depends on is checked against the installed typelib first.

Usage:
    python scripts/probe_api.py --libid
    python scripts/probe_api.py --list
    python scripts/probe_api.py --method IModelDoc2 CreateNewPart
    python scripts/probe_api.py --enum swEndConditions_e
    python scripts/probe_api.py --dump
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pythoncom

DEFAULT_TLB_DIR = Path(
    r"D:\1-master\1-software\SolidWorks-2026\Product\SOLIDWORKS"
)
SLDWORKS_TLB = "sldworks.tlb"
SWCONST_TLB = "swconst.tlb"

TKIND = {
    getattr(pythoncom, name): name
    for name in dir(pythoncom)
    if name.startswith("TKIND_")
}


def load_tlb(path: Path):
    return pythoncom.LoadTypeLib(str(path))


def iter_types(tlb):
    for index in range(tlb.GetTypeInfoCount()):
        name, _doc, _ctx, _help = tlb.GetDocumentation(index)
        ti = tlb.GetTypeInfo(index)
        try:
            attr = ti.GetTypeAttr()
        except pythoncom.com_error:
            attr = None
        yield index, name, ti, attr


def lib_info(tlb):
    guid, lcid, syskind, major, minor, flags = tlb.GetLibAttr()
    return {
        "guid": str(guid).strip("{}"),
        "lcid": lcid,
        "syskind": syskind,
        "major": major,
        "minor": minor,
        "flags": flags,
    }


VT_NAMES = {
    pythoncom.VT_EMPTY: "void",
    pythoncom.VT_NULL: "NULL",
    pythoncom.VT_I2: "short",
    pythoncom.VT_I4: "long",
    pythoncom.VT_R4: "float",
    pythoncom.VT_R8: "double",
    pythoncom.VT_CY: "CY",
    pythoncom.VT_DATE: "DATE",
    pythoncom.VT_BSTR: "BSTR",
    pythoncom.VT_DISPATCH: "IDispatch",
    pythoncom.VT_ERROR: "SCODE",
    pythoncom.VT_BOOL: "VARIANT_BOOL",
    pythoncom.VT_VARIANT: "VARIANT",
    pythoncom.VT_UNKNOWN: "IUnknown",
    pythoncom.VT_DECIMAL: "DECIMAL",
    pythoncom.VT_I1: "char",
    pythoncom.VT_UI1: "byte",
    pythoncom.VT_UI2: "unsigned short",
    pythoncom.VT_UI4: "unsigned long",
    pythoncom.VT_I8: "long long",
    pythoncom.VT_UI8: "unsigned long long",
    pythoncom.VT_INT: "int",
    pythoncom.VT_UINT: "unsigned int",
    pythoncom.VT_VOID: "void",
    pythoncom.VT_HRESULT: "HRESULT",
    pythoncom.VT_PTR: "PTR",
    pythoncom.VT_SAFEARRAY: "SAFEARRAY",
    pythoncom.VT_CARRAY: "CARRAY",
    pythoncom.VT_USERDEFINED: "USERDEFINED",
    pythoncom.VT_LPSTR: "LPSTR",
    pythoncom.VT_LPWSTR: "LPWSTR",
}

PARAM_FLAGS = {1: "in", 2: "out", 4: "retval", 8: "optional", 16: "hasdefault"}

INVKIND = {1: "FUNC", 2: "PROPGET", 4: "PROPPUT", 8: "PROPPUTREF"}


def describe_element(ti, elem) -> str:
    """Recursively render a TYPEDESC tuple as a C-ish type string."""
    if isinstance(elem, int):
        return VT_NAMES.get(elem, f"vt_{elem}")
    if not isinstance(elem, tuple):
        return str(elem)
    vt = elem[0]
    if vt == pythoncom.VT_PTR and len(elem) > 1 and isinstance(elem[1], tuple):
        return describe_element(ti, elem[1]) + "*"
    if vt == pythoncom.VT_SAFEARRAY and len(elem) > 1 and isinstance(elem[1], tuple):
        return describe_element(ti, elem[1]) + "[]"
    if vt == pythoncom.VT_USERDEFINED and len(elem) > 1:
        ref = elem[1]
        try:
            rti = ti.GetRefTypeInfo(ref)
            return rti.GetDocumentation(-1)[0].split("::")[-1]
        except Exception:
            return f"typedef({ref})"
    return VT_NAMES.get(vt, f"vt_{vt}")


def member_names(ti, memid):
    try:
        return ti.GetNames(memid)
    except pythoncom.com_error:
        return ()


def describe_method(ti, funcdesc) -> dict:
    memid = funcdesc.memid
    names = member_names(ti, memid)
    params = []
    for i, arg in enumerate(funcdesc.args):
        elem = arg[0] if isinstance(arg, tuple) else arg
        flags = arg[1] if isinstance(arg, tuple) and len(arg) > 1 else 0
        pname = names[i + 1] if i + 1 < len(names) else f"arg{i}"
        params.append(
            {
                "name": pname,
                "type": describe_element(ti, elem),
                "flags": [v for k, v in PARAM_FLAGS.items() if flags & k],
            }
        )
    return {
        "name": names[0] if names else f"memid_{memid}",
        "memid": memid,
        "invkind": INVKIND.get(funcdesc.invkind, str(funcdesc.invkind)),
        "cParams": len(funcdesc.args),
        "params": params,
        "return": describe_element(ti, funcdesc.rettype[0]),
        "help": ti.GetDocumentation(memid)[1] or "",
    }


def find_member(ti, member_name: str):
    name = member_name.split("::")[-1]
    for i in range(ti.GetTypeAttr().cFuncs):
        funcdesc = ti.GetFuncDesc(i)
        names = member_names(ti, funcdesc.memid)
        if names and names[0] == name:
            return funcdesc
    return None


def describe_enum(ti) -> dict:
    members = {}
    for i in range(ti.GetTypeAttr().cVars):
        vardesc = ti.GetVarDesc(i)
        name = member_names(ti, vardesc.memid)
        value = None
        for attr in ("value", "lpvarValue", "lpVarValue"):
            raw = getattr(vardesc, attr, None)
            if raw is not None:
                value = raw
                break
        if value is None:
            try:
                elem = vardesc.elemdescVar
                if isinstance(elem, tuple) and len(elem) >= 2:
                    value = elem[1]
            except Exception:
                pass
        if isinstance(value, tuple):
            value = value[-1]
        members[name[0] if name else f"var{i}"] = value
    return members


def dump_all(tlb, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    interfaces = {}
    for _index, name, ti, attr in iter_types(tlb):
        if attr is None:
            continue
        kind = TKIND.get(attr.typekind, str(attr.typekind))
        entry = {"kind": kind, "members": {}}
        if kind == "TKIND_ENUM":
            entry["members"] = describe_enum(ti)
        elif kind in ("TKIND_DISPATCH", "TKIND_INTERFACE"):
            for i in range(attr.cFuncs):
                funcdesc = ti.GetFuncDesc(i)
                info = describe_method(ti, funcdesc)
                entry["members"][info["name"]] = info
        else:
            entry = {"kind": kind}
        interfaces[name] = entry
    (out_dir / "sldworks.json").write_text(
        json.dumps(interfaces, indent=1), encoding="utf-8"
    )
    print(f"wrote {out_dir / 'sldworks.json'} ({len(interfaces)} types)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tlb-dir", type=Path, default=DEFAULT_TLB_DIR)
    parser.add_argument("--libid", action="store_true", help="print LIBID/version")
    parser.add_argument("--list", action="store_true", help="list all type names")
    parser.add_argument(
        "--method", nargs=2, metavar=("ITYPE", "MEMBER"), help="describe a member"
    )
    parser.add_argument("--enum", metavar="ENUM", help="dump enum members")
    parser.add_argument(
        "--dump", nargs="?", const="artifacts/probe", metavar="OUT_DIR",
        help="dump full typelib to JSON",
    )
    parser.add_argument(
        "--search", metavar="REGEX", help="search member names across all types"
    )
    args = parser.parse_args()

    tlb_path = args.tlb_dir / SLDWORKS_TLB
    if not tlb_path.exists():
        print(f"typelib not found: {tlb_path}", file=sys.stderr)
        return 2
    tlb = load_tlb(tlb_path)

    if args.libid:
        print(json.dumps(lib_info(tlb), indent=2))
        return 0

    if args.search:
        import re

        rx = re.compile(args.search, re.I)
        hits = 0
        for _index, name, ti, attr in iter_types(tlb):
            if attr is None or TKIND.get(attr.typekind) not in (
                "TKIND_DISPATCH",
                "TKIND_INTERFACE",
            ):
                continue
            for i in range(attr.cFuncs):
                funcdesc = ti.GetFuncDesc(i)
                names = member_names(ti, funcdesc.memid)
                if not names or not rx.search(names[0]):
                    continue
                sig = ", ".join(
                    p["type"] for p in describe_method(ti, funcdesc)["params"]
                )
                print(f"{name.split('::')[-1]}.{names[0]}({sig})")
                hits += 1
        print(f"# {hits} matches", file=sys.stderr)
        return 0

    if args.list or args.method or args.dump:
        for _index, name, ti, attr in iter_types(tlb):
            if args.list:
                kind = TKIND.get(attr.typekind, "?") if attr else "?"
                print(f"{name}\t{kind}")
            elif args.method and name.split("::")[-1] == args.method[0]:
                member = args.method[1]
                if member == "*":
                    for funcdesc in ti.GetFuncDesc:
                        print(json.dumps(describe_method(ti, funcdesc), indent=1))
                else:
                    funcdesc = find_member(ti, member)
                    if funcdesc is None:
                        print(f"{member} not found on {name}", file=sys.stderr)
                        return 1
                    print(json.dumps(describe_method(ti, funcdesc), indent=1))
                return 0
        if args.list:
            return 0
        if args.dump:
            dump_all(tlb, Path(args.dump))
            return 0
        print(f"type {args.method[0]} not found", file=sys.stderr)
        return 1

    if args.enum:
        const_tlb = load_tlb(args.tlb_dir / SWCONST_TLB)
        for _index, name, ti, attr in iter_types(const_tlb):
            if name.split("::")[-1] == args.enum or name == args.enum:
                print(json.dumps(describe_enum(ti), indent=1))
                return 0
        print(f"enum {args.enum} not found", file=sys.stderr)
        return 1

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
