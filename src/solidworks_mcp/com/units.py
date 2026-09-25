"""Unit conversion at the COM boundary.

Tool parameters are millimetres and degrees; the SOLIDWORKS COM API is metres
and radians. Conversion happens here and nowhere else.
"""
from __future__ import annotations

import math

MM_PER_M = 1000.0


def mm_to_m(value: float) -> float:
    return float(value) / MM_PER_M


def m_to_mm(value: float) -> float:
    return float(value) * MM_PER_M


def m2_to_mm2(value: float) -> float:
    return float(value) * MM_PER_M * MM_PER_M


def m3_to_mm3(value: float) -> float:
    return float(value) * MM_PER_M * MM_PER_M * MM_PER_M


def deg_to_rad(value: float) -> float:
    return math.radians(float(value))


def rad_to_deg(value: float) -> float:
    return math.degrees(float(value))


def point_to_mm(point) -> list[float]:
    return [m_to_mm(v) for v in point]
