import tomllib
from pathlib import Path

from solidworks_mcp import skills


def test_install_skills_copies_the_iso_workflow(tmp_path):
    installed = skills.install_skills(tmp_path)

    names = {path.parent.name for path in installed}
    assert {
        "dnk-solidworks-iso-engineering-drawing",
        "dnk-solidworks-cad-house-standard",
        "dnk-solidworks-drawing-acceptance",
        "dnk-solidworks-sheet-layout",
        "dnk-solidworks-cad-remodel",
        "dnk-solidworks-image-assisted-modeling",
    } <= names
    manifest = tmp_path / "dnk-solidworks-iso-engineering-drawing" / "SKILL.md"
    assert manifest.is_file()
    assert manifest.read_text(encoding="utf-8").startswith("---")
    image_manifest = tmp_path / "dnk-solidworks-image-assisted-modeling" / "SKILL.md"
    assert image_manifest.is_file()
    assert image_manifest.read_text(encoding="utf-8").startswith("---")


def test_install_skills_refreshes_existing_files(tmp_path):
    skills.install_skills(tmp_path)
    manifest = tmp_path / "dnk-solidworks-iso-engineering-drawing" / "SKILL.md"
    manifest.write_text("stale", encoding="utf-8")

    skills.install_skills(tmp_path)

    assert manifest.read_text(encoding="utf-8").startswith("---")


def test_install_skills_finds_wheel_data_files(monkeypatch, tmp_path):
    install_prefix = tmp_path / "venv"
    fake_module = (
        install_prefix
        / "Lib"
        / "site-packages"
        / "solidworks_mcp"
        / "skills.py"
    )
    packaged_skill = (
        install_prefix
        / "share"
        / "dnk-mcp-solidworks"
        / "skills"
        / "dnk-solidworks-image-assisted-modeling"
        / "SKILL.md"
    )
    packaged_skill.parent.mkdir(parents=True)
    packaged_skill.write_text(
        "---\nname: dnk-solidworks-image-assisted-modeling\n---\n", encoding="utf-8"
    )

    monkeypatch.setattr(skills, "__file__", str(fake_module))
    monkeypatch.setattr(
        skills.sysconfig, "get_path", lambda _name: str(install_prefix)
    )
    monkeypatch.delenv("SW_MCP_SKILLS_DIR", raising=False)

    installed = skills.install_skills(tmp_path / "agent-skills")

    assert installed == [
        tmp_path / "agent-skills" / "dnk-solidworks-image-assisted-modeling" / "SKILL.md"
    ]


def test_every_source_skill_is_declared_as_wheel_data():
    repository_root = Path(__file__).resolve().parents[2]
    project = tomllib.loads(
        (repository_root / "pyproject.toml").read_text(encoding="utf-8")
    )
    data_files = project["tool"]["setuptools"]["data-files"]
    packaged = {
        key.rsplit("/", maxsplit=1)[-1]
        for key, files in data_files.items()
        if key.startswith("share/dnk-mcp-solidworks/skills/")
        and files == [f"skills/{key.rsplit('/', maxsplit=1)[-1]}/SKILL.md"]
    }
    source = {
        path.parent.name
        for path in (repository_root / "skills").glob("*/SKILL.md")
    }

    assert source <= packaged
