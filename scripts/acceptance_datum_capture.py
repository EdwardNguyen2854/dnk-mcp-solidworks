"""Live capture acceptance on a disposable part; never saves engineer documents."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
OUT = Path(tempfile.mkdtemp(prefix="datum-capture-probe-")).resolve()
os.environ["SW_MCP_OUTPUT_ROOT"] = str(OUT)

from PIL import Image, ImageChops, ImageStat
from solidworks_mcp.com import binding
from solidworks_mcp.com.worker import ComWorker, run, set_worker
from solidworks_mcp.domain import session
from solidworks_mcp.errors import PathNotAllowedError
from solidworks_mcp.tools import core


def call(tool_name, **args):
    result = getattr(core, tool_name)(args)
    if not result.get("ok"):
        raise RuntimeError(f"{tool_name}: {result}")
    return result.get("data", {})


def mean_diff(a: Path, b: Path) -> float:
    with Image.open(a) as left, Image.open(b) as right:
        return ImageStat.Stat(ImageChops.difference(left.convert("RGB"), right.convert("RGB"))).mean[0]


def main():
    title = None
    try:
        call("new_document", kind="part")
        title = run(lambda: session.doc_info(session.active_doc("part")[1])["title"])
        call("create_sketch", plane="front")
        call("sketch_rectangle", x1_mm=0, y1_mm=0, x2_mm=100, y2_mm=60)
        call("exit_sketch")
        call("boss_extrude", depth_mm=25, name="DatumCaptureProbe")
        call("set_view", view="trimetric")
        current = call("capture_screenshot", path="probe/current.png", view="current", width=1280, height=720)
        image_path = Path(current["path"]).resolve()
        assert image_path.is_relative_to(OUT) and image_path.is_file()
        assert image_path.suffix.lower() == ".png" and current["size_bytes"] > 0
        with Image.open(image_path) as image:
            assert image.size == (1280, 720) and image.format == "PNG"
        print(f"PASS current capture size={current['size_bytes']} dimensions=1280x720 format=PNG pillow={Image.__version__}")

        # A/B/front comparison is a visual proxy because SOLIDWORKS exposes no camera getter.
        call("capture_screenshot", path="probe/before.png", view="current", width=640, height=360)
        call("capture_screenshot", path="probe/front.png", view="front", width=640, height=360)
        call("capture_screenshot", path="probe/after.png", view="current", width=640, height=360)
        a, f, b = (OUT / "probe" / f"{name}.png" for name in ("before", "front", "after"))
        d_same, d_front = mean_diff(b, a), mean_diff(b, f)
        assert d_front < d_same, f"camera proxy inconclusive: after-before={d_same:.3f}, after-front={d_front:.3f}"
        print(f"PASS current-view camera proxy after-before={d_same:.3f} after-front={d_front:.3f} (not a camera read-back)")

        nested = call("capture_screenshot", path="probe/nested/current.png", view="current", width=320, height=180)
        assert Path(nested["path"]).resolve().is_relative_to(OUT)
        print("PASS nested relative path accepted under SW_MCP_OUTPUT_ROOT")
        try:
            call("capture_screenshot", path=str(OUT.parent / "outside-datum-probe.png"), view="current", width=320, height=180)
        except PathNotAllowedError:
            print("PASS absolute path outside SW_MCP_OUTPUT_ROOT rejected")
        else:
            raise AssertionError("outside output-root path was not rejected")
        print(f"RESULT PASS; output_root={OUT}; SOLIDWORKS {run(lambda: binding.value(session.app().RevisionNumber))}")
    finally:
        if title is not None:
            run(lambda: session.app().CloseDoc(title))


if __name__ == "__main__":
    worker = ComWorker(timeout=60)
    worker.start()
    set_worker(worker)
    try:
        main()
    finally:
        worker.stop()
