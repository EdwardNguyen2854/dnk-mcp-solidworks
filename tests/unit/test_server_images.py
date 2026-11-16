import asyncio

from solidworks_mcp import server


def test_screenshot_bytes_are_emitted_as_image_content(monkeypatch):
    payload = "AQIDBASE64"

    async def fake_to_thread(_function, *_args):
        return {
            "ok": True,
            "data": {"path": "review.png"},
            "_images": [{"mime": "image/png", "data": payload}],
        }

    monkeypatch.setattr(server.asyncio, "to_thread", fake_to_thread)
    content = asyncio.run(server.call_tool("capture_screenshot", {}))

    assert len(content) == 2
    assert content[0].type == "text"
    assert payload not in content[0].text
    assert content[1].type == "image"
    assert content[1].mimeType == "image/png"
    assert content[1].data == payload


def test_reference_image_bytes_are_emitted_as_image_content(monkeypatch):
    payload = "REFIMAGEBASE64"

    async def fake_to_thread(_function, *_args):
        return {
            "ok": True,
            "data": {"path": "drawing.png", "width_px": 120, "height_px": 80},
            "evidence": {"ocr_performed": False},
            "_images": [{"mime": "image/png", "data": payload}],
        }

    monkeypatch.setattr(server.asyncio, "to_thread", fake_to_thread)
    content = asyncio.run(
        server.call_tool("view_reference_image", {"path": "drawing.png"})
    )

    assert len(content) == 2
    assert payload not in content[0].text
    assert content[1].type == "image"
    assert content[1].mimeType == "image/png"
    assert content[1].data == payload
