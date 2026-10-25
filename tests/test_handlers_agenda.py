"""Smoke-тесты agenda: парсинг scope-токена, _show_scope."""

from __future__ import annotations

import pytest

from app.routers.agenda import _scope_from_token, _scope_token


@pytest.mark.parametrize("token, expected", [
    ("public", ("public", None)),
    ("chat-1001234567890", ("chat", -1001234567890)),
    ("chat123", ("chat", 123)),
    ("invalid", None),
    ("chat", None),
    ("", None),
])
def test_scope_roundtrip(token, expected):
    if expected is None:
        assert _scope_from_token(token) is None
    else:
        assert _scope_from_token(token) == expected


@pytest.mark.parametrize("scope, token", [
    (("public", None), "public"),
    (("chat", -1001234567890), "chat-1001234567890"),
])
def test_scope_token(scope, token):
    assert _scope_token(scope) == token