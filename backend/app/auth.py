"""Server-owned identities, opaque revocable sessions, and resource guards."""
import hashlib
import hmac
import re
import secrets
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .engine_port import DomainError
from .schemas import LoginResponse, User
from .storage import Store

ITERATIONS = 600_000
LOGIN_WINDOW = 300
MAX_ATTEMPTS = 10
# A missing account still performs the same password derivation.
DUMMY_HASH = f"pbkdf2_sha256${ITERATIONS}$" + "00" * 16 + "$" + "00" * 32
bearer = HTTPBearer(auto_error=False, description="Токен из POST /api/v1/auth/login")
Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]


def hash_password(password: str) -> str:
    if not 12 <= len(password) <= 256:
        raise ValueError("Пароль должен содержать от 12 до 256 символов")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, digest = encoded.split("$")
        if algorithm != "pbkdf2_sha256" or int(iterations) != ITERATIONS:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), ITERATIONS)
        return hmac.compare_digest(actual, bytes.fromhex(digest))
    except (ValueError, TypeError):
        return False


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def public_user(row) -> User:
    return User(user_id=row["user_id"], username=row["username"], role=row["role"], employee_id=row["employee_id"])


class Auth:
    def __init__(self, store: Store, ttl: int):
        self.store, self.ttl = store, ttl

    def create_user(self, username: str, password: str, role: str, employee_id: str | None = None) -> User:
        username = username.strip().lower()
        if not re.fullmatch(r"[a-z0-9_.-]{2,64}", username):
            raise ValueError("Логин: 2–64 латинские буквы, цифры, точка, дефис или подчёркивание")
        if role not in ("employee", "hr") or (role == "employee" and not employee_id):
            raise ValueError("Сотруднику требуется employee_id; роль — employee или hr")
        password_hash = hash_password(password)
        user = User(user_id="U_" + uuid.uuid4().hex, username=username, role=role, employee_id=employee_id)
        try:
            with self.store.connect(write=True) as db:
                if employee_id:
                    self.store.profile(db, employee_id)
                db.execute("INSERT INTO accounts (user_id,username,password_hash,role,employee_id) VALUES (?,?,?,?,?)",
                           (user.user_id, username, password_hash, role, employee_id))
        except sqlite3.IntegrityError as exc:
            raise ValueError("Логин или профиль уже связан с учётной записью") from exc
        return user

    def set_password(self, username: str, password: str):
        encoded = hash_password(password)
        with self.store.connect(write=True) as db:
            row = db.execute("SELECT user_id FROM accounts WHERE username=?", (username.strip().lower(),)).fetchone()
            if not row:
                raise ValueError("Учётная запись не найдена")
            db.execute("UPDATE accounts SET password_hash=? WHERE user_id=?", (encoded, row["user_id"]))
            db.execute("DELETE FROM sessions WHERE user_id=?", (row["user_id"],))

    def disable_user(self, username: str):
        with self.store.connect(write=True) as db:
            row = db.execute("SELECT user_id FROM accounts WHERE username=?", (username.strip().lower(),)).fetchone()
            if not row:
                raise ValueError("Учётная запись не найдена")
            db.execute("UPDATE accounts SET is_active=0 WHERE user_id=?", (row["user_id"],))
            db.execute("DELETE FROM sessions WHERE user_id=?", (row["user_id"],))

    def login(self, username: str, password: str) -> LoginResponse:
        username = username.strip().lower()
        now = int(time.time())
        scope = hashlib.sha256(username.encode()).hexdigest()
        # Reserve a login attempt before the expensive hash, also across workers.
        with self.store.connect(write=True) as db:
            db.execute("DELETE FROM login_attempts WHERE window_start<=?", (now - LOGIN_WINDOW,))
            attempt = db.execute("SELECT attempts FROM login_attempts WHERE scope=?", (scope,)).fetchone()
            if attempt and attempt["attempts"] >= MAX_ATTEMPTS:
                raise DomainError(429, "login_throttled", "Слишком много попыток входа. Повторите через 5 минут")
            db.execute("INSERT INTO login_attempts VALUES (?,?,1) ON CONFLICT(scope) DO UPDATE SET attempts=attempts+1", (scope, now))
            row = db.execute("SELECT * FROM accounts WHERE username=?", (username,)).fetchone()
        valid = verify_password(password, row["password_hash"] if row else DUMMY_HASH)
        if not valid or row is None or not row["is_active"]:
            raise DomainError(401, "invalid_credentials", "Неверный логин или пароль")
        token = secrets.token_urlsafe(32)
        expires = int(time.time()) + self.ttl
        with self.store.connect(write=True) as db:
            # A password reset / disabling during verification cannot issue a session.
            current = db.execute("SELECT * FROM accounts WHERE user_id=?", (row["user_id"],)).fetchone()
            if not current or not current["is_active"] or current["password_hash"] != row["password_hash"]:
                raise DomainError(401, "invalid_credentials", "Неверный логин или пароль")
            db.execute("DELETE FROM sessions WHERE expires_at<=?", (int(time.time()),))
            db.execute("INSERT INTO sessions VALUES (?,?,?)", (token_digest(token), row["user_id"], expires))
            db.execute("DELETE FROM login_attempts WHERE scope=?", (scope,))
            user = public_user(current)
        return LoginResponse(access_token=token, expires_at=datetime.fromtimestamp(expires, timezone.utc), user=user)

    def user_for_token(self, token: str) -> User:
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            raise DomainError(401, "invalid_session", "Войдите в систему")
        with self.store.connect() as db:
            row = db.execute("""SELECT a.* FROM sessions s JOIN accounts a ON a.user_id=s.user_id
                                WHERE s.token_hash=? AND s.expires_at>? AND a.is_active=1""",
                             (token_digest(token), int(time.time()))).fetchone()
        if row is None:
            raise DomainError(401, "invalid_session", "Сессия истекла или отозвана; войдите снова")
        return public_user(row)

    def logout(self, token: str):
        with self.store.connect(write=True) as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (token_digest(token),))


def require_user(request: Request, credentials: Credentials) -> User:
    if credentials is None:
        raise DomainError(401, "authentication_required", "Войдите в систему")
    return request.app.state.auth.user_for_token(credentials.credentials)


CurrentUser = Annotated[User, Depends(require_user)]


def require_hr(user: CurrentUser) -> User:
    if user.role != "hr":
        raise DomainError(403, "hr_required", "Доступ разрешён только HR")
    return user


def require_profile_access(employee_id: str, user: CurrentUser) -> User:
    if user.role != "hr" and user.employee_id != employee_id:
        raise DomainError(403, "profile_forbidden", "Нет доступа к данным этого сотрудника")
    return user


def require_own_profile(employee_id: str, user: CurrentUser) -> User:
    if user.employee_id != employee_id:
        raise DomainError(403, "completion_forbidden", "Можно выполнять активности только своего профиля")
    return user
