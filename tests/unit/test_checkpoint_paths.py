"""Checkpoint path/type helpers.

The regression these cover: an unsaved document returns ``""`` from
GetPathName, and ``Path("")`` is ``Path(".")`` — which exists, so the old
``source.exists()`` test tried to copy the current directory and failed with
"Permission denied: '.'".
"""
from pathlib import Path

from solidworks_mcp.tx import checkpoint


class _StubDoc:
    def __init__(self, path):
        self.GetPathName = path


def test_empty_path_is_not_a_saved_file():
    source = checkpoint._saved_path(_StubDoc(""))
    assert source == Path(".")
    assert not source.is_file()


def test_none_path_is_not_a_saved_file():
    assert not checkpoint._saved_path(_StubDoc(None)).is_file()


def test_real_path_is_kept():
    source = checkpoint._saved_path(_StubDoc(r"C:\work\plate.sldprt"))
    assert source == Path(r"C:\work\plate.sldprt")


def test_open_type_follows_the_checkpoint_suffix():
    # OpenDoc6 auto-detect (0) fails on SW2026 SP0.0; each suffix must map
    # to the typed open that open_document already uses.
    assert checkpoint._open_type_for(Path("c.sldprt")) == 1
    assert checkpoint._open_type_for(Path("c.sldasm")) == 2
    assert checkpoint._open_type_for(Path("c.slddrw")) == 3
    assert checkpoint._open_type_for(Path("c.unknown")) == 0


def test_unsaved_checkpoint_extension_matches_document_kind():
    assert checkpoint.CHECKPOINT_SUFFIX_BY_KIND["part"] == ".sldprt"
    assert checkpoint.CHECKPOINT_SUFFIX_BY_KIND["assembly"] == ".sldasm"
    assert checkpoint.CHECKPOINT_SUFFIX_BY_KIND["drawing"] == ".slddrw"
