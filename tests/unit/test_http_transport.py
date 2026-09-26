from solidworks_mcp.http_transport import build_streamable_http_app, is_loopback_host


def test_loopback_hosts_are_allowed():
    assert is_loopback_host("127.0.0.1")
    assert is_loopback_host("localhost")
    assert is_loopback_host("::1")
    assert is_loopback_host("[::1]")


def test_non_loopback_hosts_are_rejected():
    assert not is_loopback_host("0.0.0.0")
    assert not is_loopback_host("192.168.1.20")
    assert not is_loopback_host("example.test")


def test_streamable_http_app_mounts_mcp_path():
    app = build_streamable_http_app(object(), path="/mcp")
    assert any(route.path == "/mcp" for route in app.routes)
