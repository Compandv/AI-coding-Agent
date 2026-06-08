import pytest

from mewcode.mcp.jsonrpc import (
    JSONRPCError,
    decode_message,
    encode_message,
    make_error_response,
    make_notification,
    make_request,
    make_success_response,
    response_error,
    response_id,
)


def test_jsonrpc_encodes_request_and_notification():
    request = make_request(1, "tools/list", {})
    notification = make_notification("notifications/initialized")

    assert request == {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    assert notification == {"jsonrpc": "2.0", "method": "notifications/initialized"}
    assert '"id"' not in encode_message(notification)


def test_jsonrpc_decodes_success_response_and_matches_id():
    message = decode_message(encode_message(make_success_response("abc", {"ok": True})))

    assert response_id(message) == "abc"
    assert message["result"] == {"ok": True}


def test_jsonrpc_decodes_error_response_details():
    message = decode_message(encode_message(make_error_response(2, -32601, "Method not found", {"method": "x"})))
    error = response_error(message)

    assert error is not None
    assert error.code == -32601
    assert error.message == "Method not found"
    assert error.data == {"method": "x"}


def test_jsonrpc_rejects_invalid_messages():
    with pytest.raises(JSONRPCError):
        decode_message('{"jsonrpc":"1.0","method":"x"}')
    with pytest.raises(JSONRPCError):
        decode_message("[]")
    with pytest.raises(JSONRPCError):
        decode_message('{"jsonrpc":"2.0","id":1}')
