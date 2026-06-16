"""
In-memory session store.

Stores { session_id -> { session_token, security_token, created_at } }.

For production: replace with a Redis-backed implementation using the same
interface so main.py requires zero changes.
"""

import logging
import time
from threading import Lock
from typing import Optional

log = logging.getLogger("acc_backend.store")

# Sessions expire after 30 minutes of inactivity (ACC default is similar)
_TTL_SECONDS = 30 * 60


class SessionStore:
    def __init__(self, ttl: int = _TTL_SECONDS):
        self._store: dict[str, dict] = {}
        self._lock = Lock()
        self._ttl = ttl

    # ------------------------------------------------------------------
    def set(self, session_id: str, *, session_token: str, security_token: str,
            login: str = "") -> None:
        with self._lock:
            self._store[session_id] = {
                "session_token": session_token,
                "security_token": security_token,
                "login": login,
                "created_at": time.monotonic(),
            }
        log.debug("Session stored: %s", session_id)

    # ------------------------------------------------------------------
    def get(self, session_id: str) -> Optional[dict]:
        with self._lock:
            entry = self._store.get(session_id)
            if entry is None:
                return None
            if time.monotonic() - entry["created_at"] > self._ttl:
                del self._store[session_id]
                log.debug("Session expired and removed: %s", session_id)
                return None
            return entry

    # ------------------------------------------------------------------
    def delete(self, session_id: str) -> None:
        with self._lock:
            self._store.pop(session_id, None)
        log.debug("Session deleted: %s", session_id)

    # ------------------------------------------------------------------
    def purge_expired(self) -> int:
        """Remove all expired sessions; returns count removed."""
        now = time.monotonic()
        with self._lock:
            expired = [k for k, v in self._store.items() if now - v["created_at"] > self._ttl]
            for k in expired:
                del self._store[k]
        if expired:
            log.info("Purged %d expired session(s)", len(expired))
        return len(expired)
