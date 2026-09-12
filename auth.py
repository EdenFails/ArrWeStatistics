import time
import secrets
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError
from fastapi import Request, HTTPException, status

SALT_PEPPER = "EdensArrWeStats"
SESSION_LIFETIME = 86400

_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=2,
    hash_len=32,
    salt_len=16,
)

_sessions: dict[str, dict[str, float]] = {}


def hash_pw(pw: str) -> str:
    if not pw:
        raise ValueError("Password cannot be empty")
    return _hasher.hash(f"{pw}{SALT_PEPPER}")


def check_pw(pw: str, hashed: str) -> bool:
    if not pw or not hashed:
        return False
    try:
        return _hasher.verify(hashed, f"{pw}{SALT_PEPPER}")
    except (VerifyMismatchError, InvalidHashError):
        return False
    except Exception:
        return False


def clean_expired_sessions() -> None:
    now = time.time()
    dead = [k for k, v in _sessions.items() if now >= v.get("exp", 0)]
    for k in dead:
        _sessions.pop(k, None)


def new_session() -> str:
    clean_expired_sessions()
    tok = secrets.token_urlsafe(32)
    now = time.time()
    _sessions[tok] = {
        "created": now,
        "exp": now + SESSION_LIFETIME,
        "seen": now,
    }
    return tok


def is_session_valid(tok: str | None) -> bool:
    if not tok or tok not in _sessions:
        return False
    now = time.time()
    entry = _sessions[tok]
    if now > entry.get("exp", 0):
        _sessions.pop(tok, None)
        return False
    entry["seen"] = now
    return True


def end_session(tok: str | None) -> None:
    if tok:
        _sessions.pop(tok, None)


def pull_token(req: Request) -> str | None:
    tok = req.cookies.get("session_token")
    if tok:
        return tok
    hdr = req.headers.get("Authorization")
    if hdr and hdr.startswith("Bearer "):
        return hdr[7:].strip()
    return None


def require_auth(req: Request) -> bool:
    tok = pull_token(req)
    if not is_session_valid(tok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return True


hash_password = hash_pw
verify_password = check_pw
create_session = new_session
validate_session = is_session_valid
revoke_session = end_session
extract_token_from_request = pull_token
SESSION_TTL_SECONDS = SESSION_LIFETIME
