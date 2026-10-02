import pytest

from solidworks_mcp.domain import features, inspect, sketch
from solidworks_mcp.errors import ComCallError, InvalidParameterError, SelectionError


def test_maximum_mass_properties_decode_documented_si_array(monkeypatch):
    from types import SimpleNamespace

    default = SimpleNamespace(Density=7800, Volume=0.00015, Area=0.02,
                              Mass=1.17, CenterOfMass=(0.05, 0.03, 0.0125))
    extension = SimpleNamespace(
        CreateMassProperty=lambda: default,
        GetMassProperties2=lambda accuracy, status, selected: (
            (0.05, 0.03, 0.0125, 0.00015, 0.02, 1.17, 0, 0, 0, 0, 0, 0), 0
        ),
    )
    monkeypatch.setattr(inspect.binding, "wrap", lambda value, interface: value)
    result = inspect.mass_properties(SimpleNamespace(Extension=extension), "maximum")
    assert result["center_of_mass_mm"] == [50, 30, 12.5]
    assert result["volume_mm3"] == 150000
    assert result["area_mm2"] == 20000
    assert result["mass_g"] == 1170
    assert result["status"] == 0


def test_hole_edge_selection_uses_closed_circle_center(monkeypatch):
    monkeypatch.setattr(inspect, "list_edges", lambda doc: [
        {"index": 0, "curve": "circle", "length_mm": 31.41592654,
         "closed": True, "center_mm": [30, 40, 0]},
        {"index": 1, "curve": "circle", "length_mm": 31.41592654,
         "closed": True, "center_mm": [30, 40, 20]},
        {"index": 2, "curve": "circle", "length_mm": 31.41592654,
         "closed": True, "center_mm": [90, 40, 20]},
    ])
    assert features._find_hole_top_edge(object(), 10, [30, 40, 20], 2) == 1


class StubFace:
    """Just enough IFace2 shape for the offset mapping (no COM)."""

    def __init__(self, box, normal):
        self._box = box
        self.Normal = normal

    def GetBox(self):
        return self._box

    def GetTessTriangles(self, _system_units):
        axis = max(range(3), key=lambda index: abs(self.Normal[index]))
        axes = [index for index in range(3) if index != axis]
        fixed = (self._box[axis] + self._box[axis + 3]) / 2.0
        points = []
        for first, second in (
            (self._box[axes[0]], self._box[axes[1]]),
            (self._box[axes[0] + 3], self._box[axes[1]]),
            (self._box[axes[0] + 3], self._box[axes[1] + 3]),
            (self._box[axes[0]], self._box[axes[1] + 3]),
        ):
            point = [0.0, 0.0, 0.0]
            point[axis] = fixed
            point[axes[0]] = first
            point[axes[1]] = second
            points.append(point)
        return [value for point in (
            points[0], points[1], points[2], points[0], points[2], points[3]
        ) for value in point]


def test_offsets_map_to_front_facing_face():
    face = StubFace([0.0, 0.0, 0.025, 0.1, 0.06, 0.025], [0.0, 0.0, 1.0])
    assert features.face_point_from_offsets(face, 50, 30) == [0.05, 0.03, 0.025]


def test_offsets_map_to_side_face():
    face = StubFace([0.1, 0.0, 0.0, 0.1, 0.06, 0.025], [1.0, 0.0, 0.0])
    assert features.face_point_from_offsets(face, 30, 12) == [0.1, 0.03, 0.012]


def test_offsets_keep_ascending_model_axis_direction_on_negative_face():
    face = StubFace([0.0, 0.0, 0.0, 0.1, 0.06, 0.0], [0.0, 0.0, -1.0])
    assert features.face_point_from_offsets(face, 25, 15) == [0.025, 0.015, 0.0]


def test_offsets_outside_the_face_are_rejected():
    face = StubFace([0.0, 0.0, 0.025, 0.1, 0.06, 0.025], [0.0, 0.0, 1.0])
    with pytest.raises(InvalidParameterError):
        features.face_point_from_offsets(face, 150, 30)


def test_offsets_reject_a_trimmed_out_hole_region():
    class TrimmedFace(StubFace):
        def GetTessTriangles(self, _system_units):
            # An outer square with a square opening in the middle, tessellated
            # as four planar strips. The point (50, 50) mm lies in the void.
            triangles = []
            strips = [
                ((0, 0), (0.04, 0), (0.04, 0.1), (0, 0.1)),
                ((0.06, 0), (0.1, 0), (0.1, 0.1), (0.06, 0.1)),
                ((0.04, 0), (0.06, 0), (0.06, 0.04), (0.04, 0.04)),
                ((0.04, 0.06), (0.06, 0.06), (0.06, 0.1), (0.04, 0.1)),
            ]
            for strip in strips:
                for xy in (strip[0], strip[1], strip[2], strip[0], strip[2], strip[3]):
                    triangles.extend((xy[0], xy[1], self._box[2]))
            return triangles

    face = TrimmedFace([0, 0, 0.025, 0.1, 0.1, 0.025], [0, 0, 1])
    with pytest.raises(InvalidParameterError, match="trimmed face"):
        features.face_point_from_offsets(face, 50, 50)
    assert features.face_point_from_offsets(face, 20, 20) == [0.02, 0.02, 0.025]


def test_non_axis_aligned_face_is_rejected():
    face = StubFace([0.0, 0.0, 0.0, 0.1, 0.1, 0.1], [0.707, 0.707, 0.0])
    with pytest.raises(SelectionError):
        features.face_point_from_offsets(face, 10, 10)


def test_edge_details_uses_trimmed_vertices_and_marks_closed(monkeypatch):
    class Vertex:
        def __init__(self, point):
            self.point = point

        def GetPoint(self):
            return self.point

    class Edge:
        def __init__(self, start, end):
            self.start = start
            self.end = end

        def Evaluate(self, _parameter):
            return [1000.0, 1000.0, 1000.0]

        def GetStartVertex(self):
            return self.start

        def GetEndVertex(self):
            return self.end

    monkeypatch.setattr(inspect.binding, "wrap", lambda value, _kind: value)
    partial = inspect.edge_details(Edge(Vertex([0.0, 0.0, 0.0]), Vertex([0.1, 0.0, 0.0])))
    assert partial["start_mm"] == [0.0, 0.0, 0.0]
    assert partial["end_mm"] == [100.0, 0.0, 0.0]
    assert partial["closed"] is False
    assert partial["endpoint_source"] == "trimmed_vertices"
    closed = inspect.edge_details(Edge(None, None))
    assert closed["closed"] is True
    assert "start_mm" not in closed


def test_mass_property_accuracy_is_a_typed_choice():
    with pytest.raises(InvalidParameterError):
        inspect.mass_properties(accuracy="ultra")


def test_sampled_surface_point_triangle_distance_uses_face_and_edge_regions():
    triangle = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0))

    assert inspect._point_triangle_distance_sq((0.25, 0.25, 2.0), triangle) == pytest.approx(4.0)
    assert inspect._point_triangle_distance_sq((0.75, 0.75, 0.0), triangle) == pytest.approx(0.125)


def test_sampled_surface_distance_requires_tessellation():
    with pytest.raises(ComCallError, match="tessellation is unavailable"):
        inspect._directed_sampled_deviation([], [])


def test_model_comparison_requires_explicit_positive_tolerances_before_com():
    with pytest.raises(InvalidParameterError, match="tolerances must be finite and positive"):
        inspect.compare_model_geometry("source.sldprt", 0.0, 0.1, 0.1)


def test_sketch_diagnostics_maps_constraint_state_without_fabricating_dof():
    class UnderConstrainedSketch:
        ModelToSketchTransform = None

        @staticmethod
        def GetConstrainedStatus():
            return 2

    result = sketch._sketch_diagnostics(UnderConstrainedSketch())

    assert result["constraint_state"] == "under_constrained"
    assert result["under_constrained"] is True
    assert result["remaining_degrees_of_freedom"] is None
    assert result["degrees_of_freedom_status"] == "not_exposed_by_ISketch_typelib"


# --- Wave 1 feature-depth argument mapping (no COM) ------------------------


def test_extrude_offset_from_surface_mapping():
    args = features._extrusion_arguments(
        None, "offset_from_surface", 0.0, False, False, offset_mm=5
    )
    assert args[3] == features.END_CONDITIONS["offset_from_surface"]
    assert args[5] == pytest.approx(0.005)
    assert args[13] is True
    args = features._extrusion_arguments(
        None, "offset_from_surface", 0.0, False, False, offset_mm=-5
    )
    assert args[13] is False


def test_extrude_reference_conditions_need_no_depth():
    for condition in ("up_to_surface", "up_to_body", "up_to_vertex"):
        args = features._extrusion_arguments(None, condition, 0.0, False, False)
        assert args[3] == features.END_CONDITIONS[condition]
        assert args[5] == 0.0


def test_extrude_offset_requires_offset():
    with pytest.raises(InvalidParameterError):
        features._extrusion_arguments(
            None, "offset_from_surface", 0.0, False, False
        )


def test_both_directions_only_with_blind():
    with pytest.raises(InvalidParameterError):
        features._extrusion_arguments(10, "up_to_surface", 0.0, False, True)


def test_cut_arguments_carry_offset_reverse():
    args = features._cut_arguments(
        None, "offset_from_surface", 0.0, False, False, False, False, offset_mm=5
    )
    assert args[5] == pytest.approx(0.005)
    assert args[13] is True
    args = features._cut_arguments(
        None, "offset_from_surface", 0.0, False, False, False, False, offset_mm=-5
    )
    assert args[5] == pytest.approx(0.005)
    assert args[13] is False


def test_thin_common_maps_values():
    assert features.THIN_SIDES == {"outward": 0, "inward": 1, "mid": 2}
    args = features._thin_common(1, 10, 2, features.THIN_SIDES["mid"], False)
    assert args[3] == features.END_CONDITIONS["through_all"]
    assert args[5] == pytest.approx(0.01)
    assert args[17] == pytest.approx(0.002)
    assert args[20] == features.THIN_SIDES["mid"]


def test_thin_extrude_validation_before_com():
    with pytest.raises(InvalidParameterError):
        features.thin_extrude(depth_mm=5, thickness_mm=2, side="sideways")
    with pytest.raises(InvalidParameterError):
        features.thin_extrude(
            depth_mm=5, thickness_mm=2, end_condition="up_to_surface"
        )
    with pytest.raises(InvalidParameterError):
        features.thin_extrude(thickness_mm=2, end_condition="blind")
    with pytest.raises(InvalidParameterError):
        features.thin_extrude(depth_mm=5, thickness_mm=0)


def test_chamfer_kind_mapping():
    assert features._chamfer_arguments("equal", 30, None) == (1, 45.0, 0.0)
    assert features._chamfer_arguments("angle_distance", 30, None) == (1, 30, 0.0)
    assert features._chamfer_arguments("distance_distance", 0, 4) == (2, 0.0, 4)
    with pytest.raises(InvalidParameterError):
        features._chamfer_arguments("distance_distance", 0, None)
    with pytest.raises(InvalidParameterError):
        features._chamfer_arguments("nonsense", 0, None)


def test_cosmetic_thread_validation_before_com():
    with pytest.raises(InvalidParameterError):
        features.cosmetic_thread(edge_index=0)
