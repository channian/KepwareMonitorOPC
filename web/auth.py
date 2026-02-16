import secrets
import time
import logging
from functools import wraps
from fastapi import Request, HTTPException
from fastapi.responses import RedirectResponse


class SessionManager:
    """
    Cookie-based session 管理（記憶體儲存，適用單機部署）。
    """

    def __init__(self, secret_key=None, session_timeout=28800):
        """
        Args:
            secret_key: Cookie 簽名金鑰
            session_timeout: Session 過期時間（秒），預設 8 小時
        """
        self.secret_key = secret_key or secrets.token_hex(32)
        self.session_timeout = session_timeout
        self._sessions = {}  # session_id -> {user_id, username, role, display_name, created_at}

    def create_session(self, user_data):
        """建立新 session，回傳 session_id"""
        session_id = secrets.token_hex(32)
        self._sessions[session_id] = {
            "user_id": user_data["id"],
            "username": user_data["username"],
            "role": user_data["role"],
            "display_name": user_data.get("display_name", user_data["username"]),
            "created_at": time.time(),
        }
        return session_id

    def get_session(self, session_id):
        """取得 session 資料，過期則自動清除"""
        if not session_id or session_id not in self._sessions:
            return None
        session = self._sessions[session_id]
        if time.time() - session["created_at"] > self.session_timeout:
            del self._sessions[session_id]
            return None
        return session

    def destroy_session(self, session_id):
        """銷毀 session"""
        self._sessions.pop(session_id, None)

    def cleanup_expired(self):
        """清理所有過期 session"""
        now = time.time()
        expired = [
            sid for sid, s in self._sessions.items()
            if now - s["created_at"] > self.session_timeout
        ]
        for sid in expired:
            del self._sessions[sid]


def get_current_user(request: Request, session_manager: SessionManager):
    """從 request cookie 取得當前使用者"""
    session_id = request.cookies.get("session_id")
    if not session_id:
        return None
    return session_manager.get_session(session_id)


def require_login(request: Request, session_manager: SessionManager):
    """要求登入，未登入則回傳 None（由 route 處理重導向）"""
    return get_current_user(request, session_manager)


def require_admin(request: Request, session_manager: SessionManager):
    """要求 admin 權限"""
    user = get_current_user(request, session_manager)
    if user and user["role"] == "admin":
        return user
    return None
