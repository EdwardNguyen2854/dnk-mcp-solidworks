import pytest

from solidworks_mcp.domain import features
from solidworks_mcp.errors import InvalidParameterError, SelectionError


class StubFace:
    """Just enough IFace2 shape for the offset mapping (no COM)."""

    def __init__(self, box, normal):
        self._box = box
        self.Normal = normal

    def GetBox(self):
        return self._box


def test_offsets_map_to_front_facing_face():
    face = StubFace([0.0, 0.0, 0.025, 0.1, 0.06, 0.025], [0.0, 0.0, 1.0])
    assert features.face_point_from_offsets(face, 50, 30) == [0.05, 0.03, 0.025]


def test_offsets_map_to_side_face():
    face = StubFace([0.1, 0.0, 0.0, 0.1, 0.06, 0.025], [1.0, 0.0, 0.0])
    assert features.face_point_from_offsets(face, 30, 12) == [0.1, 0.03, 0.012]


def test_offsets_outside_the_face_are_rejected():
    face = StubFace([0.0, 0.0, 0.025, 0.1, 0.06, 0.025], [0.0, 0.0, 1.0])
    with pytest.raises(InvalidParameterError):
        features.face_point_from_offsets(face, 150, 30)


def test_non_axis_aligned_face_is_rejected():
    face = StubFace([0.0, 0.0, 0.0, 0.1, 0.1, 0.1], [0.707, 0.707, 0.0])
    with pytest.raises(SelectionError):
        features.face_point_from_offsets(face, 10, 10)
