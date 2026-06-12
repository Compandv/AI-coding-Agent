from mewcode.memory import MemoryStore


def test_memory_store_writes_markdown_note_and_index(tmp_path):
    store = MemoryStore(tmp_path, user_home=tmp_path / "home")

    note = store.add_note("project_knowledge", "MewCode uses Python.", scope="project")

    assert note is not None
    assert note.path.exists()
    assert "category: project_knowledge" in note.path.read_text(encoding="utf-8")
    assert "MewCode uses Python." in (tmp_path / ".mewcode" / "memory" / "index.md").read_text(encoding="utf-8")


def test_memory_store_skips_sensitive_content(tmp_path):
    store = MemoryStore(tmp_path, user_home=tmp_path / "home")

    note = store.add_note("user_preference", "api_key=secret", scope="user")

    assert note is None
    assert store.list_notes() == []


def test_memory_store_skips_duplicate_note(tmp_path):
    store = MemoryStore(tmp_path, user_home=tmp_path / "home")

    first_note = store.add_note("project_knowledge", "MewCode uses Python.", scope="project")
    second_note = store.add_note("project_knowledge", "MewCode uses Python.", scope="project")

    assert first_note is not None
    assert second_note is None
    assert len(store.list_notes("project")) == 1


def test_memory_store_deletes_note_and_refreshes_index(tmp_path):
    store = MemoryStore(tmp_path, user_home=tmp_path / "home")
    note = store.add_note("user_preference", "Prefer narrow tests.", scope="user")
    assert note is not None

    assert store.delete(note.memory_id) is True

    assert store.list_notes() == []
