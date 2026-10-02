import base64
from io import BytesIO

import pytest
from PIL import Image

from solidworks_mcp.config import Config
from solidworks_mcp.domain import export
from solidworks_mcp.errors import InvalidParameterError


def _decoded_image(result):
    return Image.open(BytesIO(base64.b64decode(result["_images"][0]["data"])))


def test_view_reference_image_returns_oriented_png_and_metadata(tmp_path):
    path = tmp_path / "drawing.png"
    source = Image.new("RGB", (80, 40), "white")
    exif = Image.Exif()
    exif[274] = 6
    source.save(path, exif=exif)

    result = export.view_reference_image(str(path))

    assert result["data"]["path"] == str(path.resolve())
    assert result["data"]["format"] == "png"
    assert (result["data"]["width_px"], result["data"]["height_px"]) == (40, 80)
    assert result["evidence"]["orientation_corrected"] is True
    assert result["evidence"]["metadata_stripped"] is True
    assert result["evidence"]["ocr_performed"] is False
    assert result["_images"][0]["mime"] == "image/png"
    with _decoded_image(result) as image:
        assert image.size == (40, 80)
        assert "exif" not in image.info


def test_view_reference_image_returns_jpeg_image_content(tmp_path):
    path = tmp_path / "drawing.jpg"
    Image.new("RGB", (64, 32), "white").save(path, format="JPEG")

    result = export.view_reference_image(str(path))

    assert result["data"]["format"] == "jpeg"
    assert (result["data"]["width_px"], result["data"]["height_px"]) == (64, 32)
    assert result["_images"][0]["mime"] == "image/jpeg"
    with _decoded_image(result) as image:
        assert image.format == "JPEG"
        assert image.size == (64, 32)


def test_view_reference_image_resolves_relative_path_under_output_root(
    monkeypatch, tmp_path
):
    output_root = tmp_path / "output"
    output_root.mkdir()
    Image.new("RGB", (32, 16), "white").save(output_root / "drawing.png")
    monkeypatch.setattr(
        export, "get_config", lambda: Config(output_root=output_root)
    )

    result = export.view_reference_image("drawing.png")

    assert result["data"]["path"] == str((output_root / "drawing.png").resolve())


def test_view_reference_image_rejects_unsupported_format(tmp_path):
    path = tmp_path / "drawing.gif"
    Image.new("RGB", (16, 16), "white").save(path, format="GIF")

    with pytest.raises(InvalidParameterError, match="unsupported reference image format"):
        export.view_reference_image(str(path))


def test_view_reference_image_rejects_network_paths():
    with pytest.raises(InvalidParameterError, match="network image paths"):
        export.view_reference_image(r"\\server\share\drawing.png")


def test_view_reference_image_rejects_oversized_pixel_count(monkeypatch, tmp_path):
    path = tmp_path / "drawing.png"
    Image.new("RGB", (12, 12), "white").save(path)
    monkeypatch.setattr(export, "MAX_REFERENCE_IMAGE_PIXELS", 100)

    with pytest.raises(InvalidParameterError, match="pixel limit"):
        export.view_reference_image(str(path))


def test_view_reference_image_rejects_oversized_input(monkeypatch, tmp_path):
    path = tmp_path / "drawing.png"
    Image.new("RGB", (16, 16), "white").save(path)
    monkeypatch.setattr(export, "MAX_REFERENCE_IMAGE_BYTES", 1)

    with pytest.raises(InvalidParameterError, match="byte limit"):
        export.view_reference_image(str(path))
