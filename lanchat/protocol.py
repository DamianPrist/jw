"""局域网即时通信系统 — 共享协议层"""

import json
from typing import Any

# 消息类型常量
TYPE_LOGIN = "login"
TYPE_LOGIN_OK = "login_ok"
TYPE_LOGIN_FAIL = "login_fail"
TYPE_LOGOUT = "logout"
TYPE_BROADCAST = "broadcast"
TYPE_PRIVATE = "private"
TYPE_USER_ONLINE = "user_online"
TYPE_USER_OFFLINE = "user_offline"
TYPE_ERROR = "error"
TYPE_DISCONNECTED = "disconnected"

# 限制
MAX_MESSAGE_LENGTH = 64 * 1024  # 64KB
NICKNAME_MAX_LENGTH = 20
FORBIDDEN_NICKNAME_CHARS = set(" @\n\r\t")

ENCODING = "utf-8"
DELIMITER = b"\n"


def is_valid_nickname(nickname: str) -> tuple[bool, str]:
    """校验昵称合法性。返回 (是否合法, 错误原因)。"""
    if not nickname:
        return False, "昵称不能为空"
    if len(nickname) > NICKNAME_MAX_LENGTH:
        return False, f"昵称不能超过{NICKNAME_MAX_LENGTH}个字符"
    for ch in nickname:
        if ch in FORBIDDEN_NICKNAME_CHARS:
            return False, "昵称不能包含空格、@、换行等特殊字符"
    return True, ""


def pack_message(msg: dict[str, Any]) -> bytes:
    """将消息字典序列化为 JSON 并追加换行分隔符。"""
    body = json.dumps(msg, ensure_ascii=False)
    if len(body) > MAX_MESSAGE_LENGTH:
        raise ValueError(f"消息过长: {len(body)} bytes")
    return body.encode(ENCODING) + DELIMITER


def unpack_from_buffer(buffer: bytearray) -> list[dict[str, Any]]:
    """从接收缓冲区中提取所有完整的 JSON 消息。返回解析后的消息列表。"""
    messages = []
    while True:
        idx = buffer.find(DELIMITER)
        if idx == -1:
            break
        if idx > MAX_MESSAGE_LENGTH:
            del buffer[:idx + 1]  # 超长消息，丢弃
            continue
        raw = bytes(buffer[:idx])
        del buffer[:idx + 1]
        if raw:
            try:
                msg = json.loads(raw.decode(ENCODING))
                if isinstance(msg, dict):
                    messages.append(msg)
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
    return messages
