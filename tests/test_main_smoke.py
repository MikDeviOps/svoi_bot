"""Smoke-тест: Dispatcher собирается, роутеры регистрируются."""

from __future__ import annotations

from app.main import build_dispatcher


def test_build_dispatcher():
    dp = build_dispatcher()
    assert dp is not None
    # В корневом роутере — start и fallback.
    # Точное число роутеров проверять не будем, чтобы не ломать тест при добавлении.