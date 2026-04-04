import json

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
import uuid
from loguru import logger

from mybot.config.path import ensure_dir


@dataclass
class Session:
    """
    A conversation session.

    Store message in JSONL format for easy reading and persistence.
    """

    key: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_message(self, msg: dict[str, Any]) -> None:
        """Add a message to the session."""
        msg["timestamp"] = datetime.now().isoformat()
        self.messages.append(msg)
        self.updated_at = datetime.now()

    def get_history(self, max_message: int = 500) -> list[dict[str, Any]]:
        """Get session history messages."""
        sliced = self.messages[-max_message:]
        
        # Drop leading non-user messages to avoid start mid-turn when possible.
        for i, message in enumerate(sliced):
            if (message.get("role")) == "user":
                sliced = sliced[i:]
                break
        
        # Some providers reject orphan tool results if the matching assistant
        # tool_calls message fell outside the fixed-size history window.
        start = self._find_legal_start(sliced)
        if start:
            sliced = sliced[start:]
        
        out: list[dict[str, Any]] = []
        for message in sliced:
            entry: dict[str, Any] = {"role": message["role"], "content": message.get("content", "")}
            for key in ("tool_calls", "tool_call_id", "name"):
                if key in message:
                    entry[key] = message[key]
            out.append(entry)
        return out

    def get_conversations(self, max_message: int = 500) -> list[dict[str, Any]]:
        """Get conversations of current session."""
        sliced = self.messages[-max_message:]

        out: list[dict[str, Any]] = []
        for message in sliced:
            if (message.get("role")) == "user":
                out.append({"role": "user", "content": message.get("content", "")})
            if (message.get("role")) == "assistant":
                out.append({"role": "assistant", "content": message.get("content", "")})

        return out


    def clear(self) -> None:
        """Clear all messages and reset the session to initial state."""
        self.messages = []
        self.updated_at = datetime.now()


    def _find_legal_start(self, messages: list[dict[str, Any]]) -> int:
        """Find the first index where every tool result has a matching assistant tool_call."""
        start = 0
        declared: set[str] = set()
        for i, msg in enumerate(messages):
            role = msg.get("role")
            if role == "assistant":
                for tc in msg.get("tool_calls") or []:
                    if isinstance(tc, dict) and tc.get("id"):
                        declared.add(str(tc["id"]))
            elif role == "tool":
                tid = msg.get("tool_call_id")
                if tid and str(tid) not in declared:
                    start = i + 1
                    declared.clear()
                    for prev in messages[start: i + 1]:
                        if prev.get("role") == "assistant":
                            for tc in prev.get("tool_calls") or []:
                                if isinstance(tc, dict) and tc.get("id"):
                                    declared.add(str(tc["id"]))
        return start


class SessionManager:
    """
    Manages conversation session.
    """

    def __init__(self, workspace: Path) -> None:
        self._cache: dict[str, Session] = {}
        self.workspace = workspace
        self.session_dir = ensure_dir(self.workspace / "sessions")

    def get_or_create(self, key: str) -> Session:
        """
        Get an existing session or create a new one.

        Args:
            key: Session key (usually channel: chat_id).
        Returns:
            The session.
        """
        if key in self._cache:
            return self._cache[key]

        session = self._load(key)
        if session is None:
            session = Session(key)

        self._cache[key] = session
        return session

    def _load(self, key: str) -> Session | None:
        """Load a session form disk."""
        path = self._get_session_path(key)
        if not path.exists():
            return None
        try:
            messages = []
            metadata = {}
            created_at = None
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    if data.get("_type") == "metadata":
                        metadata = data.get("metadata", {})
                        created_at = datetime.fromisoformat(data.get("created_at")) if data.get("created_at") else None
                    else:
                        messages.append(data)

            return Session(
                key=key, 
                messages=messages, 
                created_at=created_at or datetime.now(), 
                metadata=metadata
            )
        except Exception as e:
            logger.error("Fail to load session file {}: {}", key, str(e))

    def save(self, session: Session) -> None:
        """Save a session to disk."""
        path = self._get_session_path(session.key)
        with open(path, "w", encoding="utf-8") as f:
            metadata_line = {
                "_type": "metadata",
                "key": session.key,
                "created_at": session.created_at.isoformat(),
                "updated_at": session.updated_at.isoformat(),
                "metadata": session.metadata
            }
            f.write(json.dumps(metadata_line, ensure_ascii=False) + "\n")
            for msg in session.messages:
                f.write(json.dumps(msg, ensure_ascii=False) + "\n")

        self._cache[session.key] = session

    def archive(self, session: Session) -> None:
        """archive a session. """
        path = self._get_session_path(session.key)
        path.rename(path.with_name(f"{uuid.uuid4()}.jsonl"))
        

    def invalidate(self, key: str) -> None:
        """Remove a session from the in-memory cache."""
        self._cache.pop(key, None)

    
    def _get_session_path(self, key: str) -> Path:
        """Get session file path."""
        return self.session_dir / f"{key}.jsonl"

