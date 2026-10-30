# app/infrastructure/redis/keys.py
from __future__ import annotations


APP_PREFIX = "svoi"
ENV = "prod"  # Можно вынести в config


def make_key(purpose: str, identifier: str) -> str:
    return f"{APP_PREFIX}:{ENV}:{purpose}:{identifier}"


class RedisKeys:
    @staticmethod
    def fsm(user_id: int, chat_id: int) -> str:
        return make_key("fsm", f"{chat_id}:{user_id}")

    @staticmethod
    def chat_member_cache(chat_id: int, user_id: int) -> str:
        return make_key("cache:member", f"{chat_id}:{user_id}")

    @staticmethod
    def group_size_cache(chat_id: int) -> str:
        return make_key("cache:group_size", str(chat_id))