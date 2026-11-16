from pathlib import Path

import pytest

from solidworks_mcp.config import Config
from solidworks_mcp.errors import InvalidParameterError, PathNotAllowedError


def make_config(tmp_path: Path) -> Config:
    return Config(
        output_root=tmp_path / "out",
        allowed_roots=[tmp_path / "extra"],
        checkpoint_root=tmp_path / "checkpoints",
    )


def test_relative_paths_resolve_under_output_root(tmp_path):
    config = make_config(tmp_path)
    resolved = config.resolve_output_path("parts/block.sldprt")
    assert resolved == (tmp_path / "out" / "parts" / "block.sldprt").resolve()


def test_absolute_path_inside_allowed_root(tmp_path):
    config = make_config(tmp_path)
    target = tmp_path / "extra" / "assembly.sldasm"
    assert config.resolve_output_path(str(target)) == target.resolve()


def test_path_outside_roots_rejected(tmp_path):
    config = make_config(tmp_path)
    with pytest.raises(PathNotAllowedError):
        config.resolve_output_path(str(tmp_path / "forbidden" / "x.stl"))


def test_invalid_tier_rejected(tmp_path):
    with pytest.raises(InvalidParameterError):
        Config(tool_tier="ultimate")


def test_template_lookup(tmp_path):
    template_dir = tmp_path / "templates"
    template_dir.mkdir()
    (template_dir / "Part.PRTDOT").write_text("x")
    config = Config(template_dir=template_dir)
    assert config.find_template("part").name == "Part.PRTDOT"
    assert config.discover_template_dir() == template_dir


def test_template_missing_raises(tmp_path, monkeypatch):
    config = Config(template_dir=tmp_path)
    monkeypatch.setattr(Config, "template_dirs", lambda self: [tmp_path])
    from solidworks_mcp.errors import PathNotFoundError

    with pytest.raises(PathNotFoundError):
        config.find_template("assembly")
