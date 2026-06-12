from mewcode.memory import MemoryContextManager
from mewcode.session import ChatSession


def test_memory_manager_skips_plain_project_question(tmp_path):
    manager = MemoryContextManager(tmp_path, user_home=tmp_path / "home")
    session = ChatSession()
    session.add_user_message("本项目用的是什么技术栈？")
    session.add_assistant_message("本项目使用 Python。")

    assert manager.remember_turn(session) == 0
    assert manager.memories.list_notes() == []


def test_memory_manager_remembers_explicit_user_preference(tmp_path):
    manager = MemoryContextManager(tmp_path, user_home=tmp_path / "home")
    session = ChatSession()
    session.add_user_message("记住，我是 Python 与 C++ 工程师。")
    session.add_assistant_message("记住了。")

    assert manager.remember_turn(session) == 1
    notes = manager.memories.list_notes("user")
    assert len(notes) == 1
    assert notes[0].category == "user_preference"
    assert "Python 与 C++ 工程师" in notes[0].content


def test_memory_manager_does_not_treat_do_not_call_tools_as_correction(tmp_path):
    manager = MemoryContextManager(tmp_path, user_home=tmp_path / "home")
    session = ChatSession()
    session.add_user_message("只回答一句，不要调用工具。")
    session.add_assistant_message("好的。")

    assert manager.remember_turn(session) == 0
    assert manager.memories.list_notes() == []


def test_memory_manager_remembers_explicit_project_fact(tmp_path):
    manager = MemoryContextManager(tmp_path, user_home=tmp_path / "home")
    session = ChatSession()
    session.add_user_message("记住，本项目的技术栈是 Python。")
    session.add_assistant_message("记住了。")

    assert manager.remember_turn(session) == 1
    notes = manager.memories.list_notes("project")
    assert len(notes) == 1
    assert notes[0].category == "project_knowledge"
    assert "本项目的技术栈是 Python" in notes[0].content
