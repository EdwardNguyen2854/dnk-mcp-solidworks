"""Assemblies: components, transforms, mates, interference."""
from __future__ import annotations

import math
from pathlib import Path

from ..com import binding, units
from ..errors import (
    ComCallError,
    FeatureBuildError,
    InvalidParameterError,
    PathNotFoundError,
    SelectionError,
)
from . import inspect, session

MATE_TYPES = {
    "coincident": 0,
    "concentric": 1,
    "perpendicular": 2,
    "parallel": 3,
    "tangent": 4,
    "distance": 5,
    "angle": 6,
}
MATE_TYPE_NAMES = {code: name for name, code in MATE_TYPES.items()}
MATE_ALIGN = {"aligned": 0, "anti_aligned": 1, "closest": 2}
DIRECTIONS = {
    "+x": (1.0, 0.0, 0.0),
    "-x": (-1.0, 0.0, 0.0),
    "+y": (0.0, 1.0, 0.0),
    "-y": (0.0, -1.0, 0.0),
    "+z": (0.0, 0.0, 1.0),
    "-z": (0.0, 0.0, -1.0),
}


def _assembly(doc):
    return binding.wrap(doc, "IAssemblyDoc")


def _component_infos(doc) -> list[dict]:
    assembly = _assembly(doc)
    infos = []
    for raw in assembly.GetComponents(False) or []:
        try:
            component = binding.wrap(raw, "IComponent2")
        except Exception:
            continue
        info: dict = {
            "name": str(binding.value(component.Name2)),
            "path": str(binding.value(component.GetPathName)),
            "fixed": bool(binding.value(component.IsFixed)),
        }
        try:
            data = [float(v) for v in binding.value(component.Transform2.ArrayData)]
            info["position_mm"] = [round(units.m_to_mm(v), 4) for v in data[9:12]]
            info["rotation_matrix"] = [round(v, 6) for v in data[0:9]]
        except Exception:
            pass
        try:
            box = binding.value(component.GetBox(False, False))
            if box and len(box) >= 6:
                info["box_mm"] = {
                    "min": [round(units.m_to_mm(v), 4) for v in box[0:3]],
                    "max": [round(units.m_to_mm(v), 4) for v in box[3:6]],
                }
        except Exception:
            pass
        infos.append(info)
    return infos


def list_components() -> list[dict]:
    _, doc, _ = session.active_doc(("assembly",))
    return _component_infos(doc)


def _find_component(doc, name: str):
    available = []
    for raw in _assembly(doc).GetComponents(False) or []:
        component = binding.wrap(raw, "IComponent2")
        current = str(binding.value(component.Name2))
        available.append(current)
        if current == name:
            return component
    raise SelectionError(f"component {name!r} not found", available=available)


def _select_component(doc, component, append: bool) -> bool:
    """Select a component: SelectByIDString first, direct Select2 as fallback.

    IComponent2.Select2 alone fails on mated or fully defined components; the
    assembly-qualified identifier from the component itself is reliable.
    """
    identifier = ""
    try:
        identifier = str(binding.value(component.GetSelectByIDString) or "")
    except Exception:
        identifier = ""
    if identifier:
        try:
            if doc.Extension.SelectByID2(
                identifier, "COMPONENT", 0, 0, 0, append, 0, None, 0
            ):
                return True
        except Exception:
            pass
    try:
        return bool(component.Select2(append, 0))
    except Exception:
        return False


def _norm(path: str) -> str:
    return str(Path(path).resolve()).lower()


def _open_component_if_needed(app, source: Path) -> str | None:
    """Load the component document if it is not already open.

    AddComponent5 silently returns null on this build when the component
    document is not already loaded in the session. Returns the title of the
    document that was opened, or None if it was already open.
    """
    for raw in app.GetDocuments() or []:
        doc = session.wrap_doc(raw)
        current = str(binding.value(doc.GetPathName))
        if current and _norm(current) == _norm(str(source)):
            return None
    from . import documents

    result = documents.open_document(str(source))
    return result["document"]["title"]


def insert_component(
    path: str,
    x_mm: float = 0.0,
    y_mm: float = 0.0,
    z_mm: float = 0.0,
    fixed: bool = False,
) -> dict:
    application, doc, _ = session.active_doc(("assembly",))
    source = Path(path).expanduser()
    if not source.exists():
        raise PathNotFoundError(f"component file not found: {source}")
    opened_title = _open_component_if_needed(application, source)
    try:
        before = {info["name"] for info in _component_infos(doc)}
        assembly = _assembly(doc)
        raw = assembly.AddComponent5(
            str(source),
            0,
            "",
            False,
            "",
            units.mm_to_m(x_mm),
            units.mm_to_m(y_mm),
            units.mm_to_m(z_mm),
        )
        component = None
        if raw is not None:
            component = binding.wrap(raw, "IComponent2")
        if component is None:
            new_names = [
                info["name"]
                for info in _component_infos(doc)
                if info["name"] not in before
            ]
            if not new_names:
                raise ComCallError(
                    f"could not insert {source}",
                    hint="The component document could not be loaded.",
                )
            component = _find_component(doc, new_names[-1])
        name = str(binding.value(component.Name2))
        # AddComponent5 places the component *centre* at the requested point;
        # re-place it so that its origin lands there instead.
        component.SetTransformAndSolve2(make_transform(application, x_mm, y_mm, z_mm))
        if fixed:
            session.clear_selection(doc)
            if _select_component(doc, component, append=False):
                assembly.FixComponent()
        infos = _component_infos(doc)
        entry = next((info for info in infos if info["name"] == name), None)
        return {"component": entry, "count": len(infos)}
    finally:
        if opened_title:
            for raw in application.GetDocuments() or []:
                other = session.wrap_doc(raw)
                if str(binding.value(other.GetTitle)) == opened_title:
                    other.SetSaveFlag()
                    application.CloseDoc(opened_title)
                    break


def make_transform(
    app,
    x_mm: float,
    y_mm: float,
    z_mm: float,
    rx_deg: float = 0.0,
    ry_deg: float = 0.0,
    rz_deg: float = 0.0,
):
    """Build a component transform (rotation rows + translation + scale)."""
    math_utility = binding.wrap(app.GetMathUtility(), "IMathUtility")
    identity = binding.r8_array(
        [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0]
    )
    transform = binding.wrap(
        math_utility.CreateTransform(identity), "IMathTransform"
    )

    def vector(values):
        return binding.wrap(
            math_utility.CreateVector(binding.r8_array(values)), "IMathVector"
        )

    rotation = _rotation_matrix(rx_deg, ry_deg, rz_deg)
    transform.SetData(
        vector(rotation[0:3]),
        vector(rotation[3:6]),
        vector(rotation[6:9]),
        vector(
            [
                units.mm_to_m(x_mm),
                units.mm_to_m(y_mm),
                units.mm_to_m(z_mm),
            ]
        ),
        1.0,
    )
    return transform


def component_position(component) -> list[float] | None:
    try:
        data = [float(v) for v in binding.value(component.Transform2.ArrayData)]
        return [round(units.m_to_mm(v), 4) for v in data[9:12]]
    except Exception:
        return None


def _rotation_matrix(rx_deg: float, ry_deg: float, rz_deg: float) -> list[float]:
    rx, ry, rz = (math.radians(v) for v in (rx_deg, ry_deg, rz_deg))
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    matrix_rx = [[1, 0, 0], [0, cx, -sx], [0, sx, cx]]
    matrix_ry = [[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]]
    matrix_rz = [[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]]

    def multiply(a, b):
        return [
            [sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)]
            for i in range(3)
        ]

    rotation = multiply(multiply(matrix_rz, matrix_ry), matrix_rx)
    return [value for row in rotation for value in row]


def set_component_transform(
    name: str,
    x_mm: float = 0.0,
    y_mm: float = 0.0,
    z_mm: float = 0.0,
    rx_deg: float = 0.0,
    ry_deg: float = 0.0,
    rz_deg: float = 0.0,
) -> dict:
    application, doc, _ = session.active_doc(("assembly",))
    component = _find_component(doc, name)
    transform = make_transform(
        application, x_mm, y_mm, z_mm, rx_deg, ry_deg, rz_deg
    )
    ok = component.SetTransformAndSolve2(transform)
    if not ok:
        ok = component.SetTransformAndSolve(transform)
    if not ok:
        raise ComCallError(f"could not place component {name!r}")
    entry = next(
        info for info in _component_infos(doc) if info["name"] == name
    )
    return {"component": entry}


def _component_face_by_direction(component, direction: str):
    target = DIRECTIONS.get(direction)
    if target is None:
        raise InvalidParameterError(
            f"unknown direction {direction!r}", available=sorted(DIRECTIONS)
        )
    try:
        body_raw = binding.value(component.GetBody())
    except Exception:
        body_raw = None
    if body_raw is None:
        raise SelectionError(
            "component has no body in memory (lightweight or suppressed?)"
        )
    body = binding.wrap(body_raw, "IBody2")
    for face in inspect._faces(body):
        try:
            normal = binding.value(face.Normal)
        except Exception:
            continue
        if not normal or len(normal) < 3:
            continue
        dot = sum(a * b for a, b in zip(normal[:3], target))
        if dot > 0.99 and inspect._surface_name(face) == "plane":
            return face
    raise SelectionError(
        f"no planar face with normal {direction} on this component"
    )


def add_mate(
    mate_type: str,
    component_a: str,
    direction_a: str,
    component_b: str,
    direction_b: str,
    distance_mm: float | None = None,
    align: str = "closest",
    flip: bool = False,
) -> dict:
    if mate_type not in MATE_TYPES:
        raise InvalidParameterError(
            f"unknown mate_type {mate_type!r}", available=sorted(MATE_TYPES)
        )
    if align not in MATE_ALIGN:
        raise InvalidParameterError(
            f"unknown align {align!r}", available=sorted(MATE_ALIGN)
        )
    _, doc, _ = session.active_doc(("assembly",))
    comp_a = _find_component(doc, component_a)
    comp_b = _find_component(doc, component_b)
    session.clear_selection(doc)
    face_a = _component_face_by_direction(comp_a, direction_a)
    if not inspect.select_entity(face_a, append=False):
        raise SelectionError(f"could not select face {direction_a} of {component_a}")
    face_b = _component_face_by_direction(comp_b, direction_b)
    if not inspect.select_entity(face_b, append=True):
        raise SelectionError(f"could not select face {direction_b} of {component_b}")
    assembly = _assembly(doc)
    result = assembly.AddMate3(
        MATE_TYPES[mate_type],
        MATE_ALIGN[align],
        flip,
        units.mm_to_m(distance_mm or 0.0),
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        False,
        0,
    )
    mate, (status,) = session.com_result(result, 1)
    if mate is None:
        raise FeatureBuildError(
            f"{mate_type} mate did not build",
            mate_status=int(status) if status is not None else None,
            hint="Check that both directions name planar faces and that a "
            "distance is supplied for distance mates.",
        )
    doc.ForceRebuild3(False)
    return {
        "mate": mate_type,
        "between": [component_a, component_b],
        "status": int(status) if status is not None else None,
        "components": _component_infos(doc),
    }


def check_interference() -> dict:
    _, doc, _ = session.active_doc(("assembly",))
    assembly = _assembly(doc)
    manager = binding.wrap(
        assembly.InterferenceDetectionManager, "IInterferenceDetectionMgr"
    )
    manager.IncludeMultibodyPartInterferences = True
    manager.TreatCoincidenceAsInterference = False
    count = int(binding.value(manager.GetInterferenceCount()))
    interferences = []
    for raw in (manager.GetInterferences() or []) if count else []:
        interference = binding.wrap(raw, "IInterference")
        entry: dict = {}
        try:
            entry["volume_mm3"] = round(
                units.m3_to_mm3(float(binding.value(interference.Volume))), 6
            )
        except Exception:
            pass
        names = []
        try:
            for raw_component in binding.value(interference.Components) or []:
                try:
                    names.append(
                        str(
                            binding.value(
                                binding.wrap(raw_component, "IComponent2").Name2
                            )
                        )
                    )
                except Exception:
                    continue
        except Exception:
            pass
        entry["components"] = names
        interferences.append(entry)
    return {"count": count, "interferences": interferences}


def assembly_bounding_box() -> dict:
    _, doc, _ = session.active_doc(("assembly",))
    assembly = _assembly(doc)
    box = binding.value(assembly.GetBox(0))
    if not box or len(box) < 6:
        raise ComCallError("the assembly has no geometry to bound")
    minimum = [round(units.m_to_mm(v), 4) for v in box[0:3]]
    maximum = [round(units.m_to_mm(v), 4) for v in box[3:6]]
    return {
        "min_mm": minimum,
        "max_mm": maximum,
        "size_mm": [round(maximum[i] - minimum[i], 4) for i in range(3)],
    }


def _mate_entry(feature) -> dict:
    entry: dict = {"name": str(binding.value(feature.Name))}
    try:
        definition = binding.wrap(feature.GetSpecificFeature2(), "IMate2")
    except Exception:
        definition = None
    if definition is None:
        return entry
    try:
        code = int(binding.value(definition.Type))
        entry["mate_type"] = MATE_TYPE_NAMES.get(code, f"type_{code}")
    except Exception:
        pass
    try:
        distance = binding.value(definition.Distance)
        if distance is not None:
            entry["distance_mm"] = round(units.m_to_mm(float(distance)), 6)
    except Exception:
        pass
    try:
        angle = binding.value(definition.Angle)
        if angle is not None:
            entry["angle_deg"] = round(units.rad_to_deg(float(angle)), 6)
    except Exception:
        pass
    entities = []
    try:
        count = int(definition.GetMateEntityCount())
    except Exception:
        count = 0
    for index in range(count):
        try:
            entity = binding.wrap(definition.MateEntity(index), "IMateEntity2")
            item = {"index": index}
            try:
                item["reference_type"] = int(binding.value(entity.ReferenceType))
            except Exception:
                pass
            try:
                component = binding.wrap(
                    entity.ReferenceComponent, "IComponent2"
                )
                item["component"] = str(binding.value(component.Name2))
            except Exception:
                pass
            entities.append(item)
        except Exception:
            continue
    if entities:
        entry["entities"] = entities
    return entry


def list_mates() -> dict:
    """Read the assembly's mates from the MateGroup feature children."""
    _, doc, _ = session.active_doc(("assembly",))
    mates = []
    for feature in session.iter_features(doc):
        try:
            if str(feature.GetTypeName2()) != "MateGroup":
                continue
        except Exception:
            continue
        try:
            child = binding.wrap(feature.GetFirstSubFeature(), "IFeature")
        except Exception:
            child = None
        guard = 0
        while child is not None and guard < 5000:
            guard += 1
            mates.append(_mate_entry(child))
            try:
                child = binding.wrap(child.GetNextSubFeature(), "IFeature")
            except Exception:
                break
    return {"mates": mates, "count": len(mates)}


def set_component_fixed(names: list[str], fixed: bool = True) -> dict:
    if not names:
        raise InvalidParameterError("component_names must not be empty")
    _, doc, _ = session.active_doc(("assembly",))
    assembly = _assembly(doc)
    session.clear_selection(doc)
    for index, name in enumerate(names):
        component = _find_component(doc, name)
        if not _select_component(doc, component, append=index > 0):
            raise SelectionError(f"could not select component {name!r}")
    if fixed:
        assembly.FixComponent()
    else:
        assembly.UnfixComponent()
    session.clear_selection(doc)
    infos = _component_infos(doc)
    selected = [
        info
        for info in infos
        if any(info["name"] == name for name in names)
    ]
    if any(info["fixed"] != bool(fixed) for info in selected):
        raise ComCallError(
            f"SOLIDWORKS did not set fixed={bool(fixed)} on every component",
            components=selected,
        )
    return {"components": selected, "fixed": bool(fixed)}
