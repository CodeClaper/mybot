import json

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from loguru import logger

from mybot.utils.helper import ensure_dir


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

    def get_history(self, max_message: int = 1000) -> list[dict[str, Any]]:
        """Get session history messages."""
        return self.messages[-max_message:]

    def clear(self) -> None:
        """Clear all messages and reset the session to initial state."""
        self.messages = []
        self.updated_at = datetime.now()


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

    
    def _get_session_path(self, key: str) -> Path:
        """Get session file path."""
        return self.session_dir / f"{key}.jsonl"

