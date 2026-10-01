import hashlib
import secrets
from pathlib import Path, PurePosixPath

from argon2 import PasswordHasher
from argon2.low_level import Type
from fastapi import HTTPException

PASSWORDS = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1, type=Type.ID)
SESSION_COOKIE = "forge_session"


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


def forbidden(code: str = "FORBIDDEN", status: int = 403):
    raise HTTPException(status_code=status, detail={"code": code})


def contained_file(root: Path, name: str) -> Path:
    """Only canonical relative source paths; reject symlinks, including within root."""
    path = PurePosixPath(name)
    if (
        not name
        or "\\" in name
        or "\x00" in name
        or path.is_absolute()
        or any(part in ("", ".", "..") for part in name.split("/"))
        or any(part.startswith(".") for part in path.parts)
    ):
        forbidden("INVALID_PATH", 400)
    resolved_root = root.resolve()
    candidate = resolved_root.joinpath(*path.parts)
    for parent in (*candidate.parents, candidate):
        if parent == resolved_root.parent:
            continue
        if parent == resolved_root or resolved_root in parent.parents:
            if parent.is_symlink():
                forbidden("INVALID_PATH", 400)
    if not candidate.resolve().is_relative_to(resolved_root):
        forbidden("INVALID_PATH", 400)
    return candidate
