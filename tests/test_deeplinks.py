"""Тесты parse_start_payload."""

from __future__ import annotations

import pytest

from app.services.deeplinks import parse_start_payload


@pytest.mark.parametrize("payload, action, event_id, chat_id", [
    (None, "none", None, None),
    ("", "none", None, None),
    ("unknown", "none", None, None),
    ("join_123", "join", 123, None),
    ("cancel_45", "cancel", 45, None),
    ("detail_7", "detail", 7, None),
    ("participants_9", "participants", 9, None),
    ("join_abc", "none", None, None),
    ("create_-1001234567890", "create", None, -1001234567890),
    ("create_abc", "none", None, None),
    ("create_1", "create", None, 1),
])
def test_parse_start_payload(payload, action, event_id, chat_id):
    link = parse_start_payload(payload)
    assert link.action == action
    assert link.event_id == event_id
    assert link.chat_id == chat_id