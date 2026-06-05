from mewcode.session import ChatSession


def test_session_stores_messages_and_returns_copy():
    session = ChatSession()
    session.add_user_message("hello")
    session.add_assistant_message("hi")

    snapshot = session.snapshot()

    assert snapshot == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]
    snapshot[0]["content"] = "changed"
    assert session.messages[0]["content"] == "hello"
