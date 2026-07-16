"""用户会话状态管理（内存，单用户场景，dict by chat_id）。"""
import threading
from dataclasses import dataclass, field
from typing import Literal

from .media_scanner import MediaEntry
from .subtitle_types import SubtitleCandidate


@dataclass
class Session:
    """单用户的交互状态机。"""
    stage: Literal["idle", "pick_dir", "pick_sub"] = "idle"
    keyword: str = ""
    entries: list[MediaEntry] = field(default_factory=list)
    entry_page: int = 0
    selected_entry: MediaEntry | None = None
    candidates: list[SubtitleCandidate] = field(default_factory=list)
    sub_page: int = 0
    force: bool = False        # -f 强制覆盖模式
    primary_available: bool = True  # 主源是否可用（提示用）


_sessions: dict[int, Session] = {}
_lock = threading.Lock()


def get_session(chat_id: int) -> Session:
    """获取或创建用户会话。"""
    with _lock:
        if chat_id not in _sessions:
            _sessions[chat_id] = Session()
        return _sessions[chat_id]


def reset_session(chat_id: int) -> None:
    """重置用户会话到 idle。"""
    with _lock:
        _sessions[chat_id] = Session()
