from solidworks_mcp import skills


def test_install_skills_copies_the_iso_workflow(tmp_path):
    installed = skills.install_skills(tmp_path)

    names = {path.parent.name for path in installed}
    assert {
        "iso-engineering-drawing",
        "cad-house-standard",
        "drawing-acceptance",
        "sheet-layout",
    } <= names
    manifest = tmp_path / "iso-engineering-drawing" / "SKILL.md"
    assert manifest.is_file()
    assert manifest.read_text(encoding="utf-8").startswith("---")


def test_install_skills_refreshes_existing_files(tmp_path):
    skills.install_skills(tmp_path)
    manifest = tmp_path / "iso-engineering-drawing" / "SKILL.md"
    manifest.write_text("stale", encoding="utf-8")

    skills.install_skills(tmp_path)

    assert manifest.read_text(encoding="utf-8").startswith("---")
