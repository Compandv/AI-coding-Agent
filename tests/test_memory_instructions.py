from mewcode.memory import InstructionLoader


def test_instruction_loader_orders_project_private_before_project_and_user(tmp_path):
    user_home = tmp_path / "home"
    project = tmp_path / "project"
    (project / ".mewcode").mkdir(parents=True)
    (user_home / ".mewcode").mkdir(parents=True)
    (project / ".mewcode" / "MEWCODE.md").write_text("private", encoding="utf-8")
    (project / "MEWCODE.md").write_text("root", encoding="utf-8")
    (user_home / ".mewcode" / "MEWCODE.md").write_text("user", encoding="utf-8")

    bundle = InstructionLoader(project, user_home=user_home).load()

    assert [file.content for file in bundle.files] == ["private", "root", "user"]
    rendered = bundle.render()
    assert rendered.index("Project private instructions") < rendered.index("Project root instructions")
    assert rendered.index("Project root instructions") < rendered.index("User global instructions")


def test_instruction_loader_expands_includes_and_blocks_escape(tmp_path):
    project = tmp_path / "project"
    (project / ".mewcode" / "rules").mkdir(parents=True)
    (project / ".mewcode" / "rules" / "python.md").write_text("python rules", encoding="utf-8")
    (tmp_path / "outside.md").write_text("secret", encoding="utf-8")
    (project / ".mewcode" / "MEWCODE.md").write_text(
        "@include ./rules/python.md\n@include ../../outside.md",
        encoding="utf-8",
    )

    bundle = InstructionLoader(project, user_home=tmp_path / "home").load()
    rendered = bundle.render()

    assert "python rules" in rendered
    assert "secret" not in rendered
    assert any("outside allowed root" in warning for warning in bundle.warnings)


def test_instruction_loader_skips_cyclic_include(tmp_path):
    project = tmp_path / "project"
    (project / ".mewcode").mkdir(parents=True)
    (project / ".mewcode" / "MEWCODE.md").write_text("@include b.md", encoding="utf-8")
    (project / ".mewcode" / "b.md").write_text("@include MEWCODE.md", encoding="utf-8")

    bundle = InstructionLoader(project, user_home=tmp_path / "home").load()

    assert any("cyclic include" in warning for warning in bundle.warnings)
