from mewcode.providers.base import ChatResponse, ToolCall
from mewcode.session import ChatSession
from mewcode.skills import SkillManager
from mewcode.skills.core import parse_skill_file
from mewcode.tools import ToolContext, default_registry
from mewcode.agent import SingleToolAgent, ToolFinished


class FakeProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete_chat(self, payload, tools=None):
        self.calls.append({"payload": payload, "tools": tools})
        return self.responses.pop(0)


def write_skill(path, name="demo", description="Demo skill", allowed="ReadFile", mode="inline", history="recent", body="Use $ARGUMENTS."):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "---",
                f"name: {name}",
                f"description: {description}",
                f"allowedTools: [{allowed}]",
                f"mode: {mode}",
                f"history: {history}",
                "---",
                body,
            ]
        ),
        encoding="utf-8",
    )


def test_parse_skill_file_frontmatter_and_arguments(tmp_path):
    path = tmp_path / "demo.md"
    write_skill(path, body="Hello $ARGUMENTS")

    skill = parse_skill_file(path)

    assert skill.name == "demo"
    assert skill.allowed_tools == ("ReadFile",)
    assert skill.render("world") == "Hello world"


def test_skill_manager_three_layer_priority_and_directory_skill(tmp_path):
    builtin = tmp_path / "builtin"
    user_home = tmp_path / "home"
    project = tmp_path / "project"
    write_skill(builtin / "commit.md", name="commit", description="builtin")
    write_skill(user_home / ".mewcode" / "skills" / "commit.md", name="commit", description="user")
    directory = project / ".mewcode" / "skills" / "commit"
    write_skill(directory / "SKILL.md", name="commit", description="project", body="Project skill")
    (directory / "references").mkdir()
    (directory / "references" / "notes.md").write_text("reference text", encoding="utf-8")
    (directory / "tool.json").write_text('{"tools": ["future"]}', encoding="utf-8")

    manager = SkillManager(project, default_registry(), user_home=user_home, builtin_dir=builtin)
    manager.load()

    skill = manager.require("commit")
    assert skill.description == "project"
    assert skill.source == "project"
    assert skill.references["notes.md"] == "reference text"
    assert skill.tool_metadata == {"tools": ["future"]}


def test_skill_manager_skips_bad_dependency(tmp_path):
    builtin = tmp_path / "builtin"
    project = tmp_path / "project"
    write_skill(builtin / "bad.md", name="bad", description="Bad", allowed="MissingTool")

    manager = SkillManager(project, default_registry(), user_home=tmp_path / "home", builtin_dir=builtin)
    manager.load()

    assert "bad" not in manager.skills
    assert manager.issues
    assert "MissingTool" in manager.issues[0].message


def test_skill_tools_list_load_and_activate(tmp_path):
    manager = SkillManager(tmp_path / "project", default_registry(), user_home=tmp_path / "home")
    manager.load()
    manager.register_tools()
    context = ToolContext(root_dir=tmp_path)

    listed = manager.registry.get("ListSkills").execute({}, context).to_message_content()
    loaded = manager.registry.get("LoadSkill").execute({"name": "commit", "arguments": "msg"}, context).to_message_content()
    activated = manager.registry.get("ActivateSkill").execute({"name": "commit"}, context).to_message_content()

    assert listed["ok"] is True
    assert any(skill["name"] == "commit" for skill in listed["metadata"]["skills"])
    assert loaded["ok"] is True
    assert "msg" in loaded["content"]
    assert activated["metadata"]["active_skills"] == ["commit"]


def test_skill_filters_provider_tools_and_blocks_execution_side(tmp_path):
    registry = default_registry()
    manager = SkillManager(tmp_path / "project", registry, user_home=tmp_path / "home")
    manager.load()
    manager.register_tools()
    manager.activate("test")
    provider = FakeProvider(
        [
            ChatResponse(text="", tool_calls=[ToolCall(name="WriteFile", arguments={"path": "x.txt", "content": "bad"})]),
            ChatResponse(text="blocked"),
        ]
    )
    agent = SingleToolAgent(
        provider=provider,
        registry=registry,
        context=ToolContext(root_dir=tmp_path),
        skill_manager=manager,
    )

    events = list(agent.stream_turn(ChatSession(), "run tests"))

    first_tools = provider.calls[0]["tools"]
    assert "WriteFile" not in {tool["name"] for tool in first_tools}
    finished = [event for event in events if isinstance(event, ToolFinished)]
    assert finished[0].result["metadata"]["blocked_by_skill"] is True


def test_skill_overlay_starts_with_summary_not_full_sop(tmp_path):
    registry = default_registry()
    manager = SkillManager(tmp_path / "project", registry, user_home=tmp_path / "home")
    manager.load()
    manager.register_tools()
    provider = FakeProvider([ChatResponse(text="ok")])
    agent = SingleToolAgent(
        provider=provider,
        registry=registry,
        context=ToolContext(root_dir=tmp_path),
        skill_manager=manager,
    )

    list(agent.stream_turn(ChatSession(), "hello"))

    messages = provider.calls[0]["payload"].messages
    overlay_text = "\n".join(str(message.get("content") or "") for message in messages)
    assert "Available MewCode skills" in overlay_text
    assert "Follow this commit SOP" not in overlay_text


def test_fork_skill_returns_summary_to_main_session_without_tool_history(tmp_path):
    registry = default_registry()
    manager = SkillManager(tmp_path / "project", registry, user_home=tmp_path / "home")
    manager.load()
    manager.register_tools()
    provider = FakeProvider([ChatResponse(text="review summary")])
    agent = SingleToolAgent(
        provider=provider,
        registry=registry,
        context=ToolContext(root_dir=tmp_path),
        skill_manager=manager,
    )
    session = ChatSession()

    events = list(agent.stream_skill_command(session, "review", "security"))

    assert any("review summary" in event.text for event in events if hasattr(event, "text"))
    assert [message["role"] for message in session.messages] == ["user", "assistant"]
    assert "security" in session.messages[0]["content"]
    assert session.messages[1]["content"] == "review summary"
