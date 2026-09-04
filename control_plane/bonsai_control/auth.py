import re
import secrets

from fastapi import Header, HTTPException, status

from .settings import get_settings


def _require(expected: str, supplied: str | None, label: str) -> None:
    if supplied is None or not secrets.compare_digest(expected, supplied):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"invalid {label} token")


WORKER_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def require_lab(
    x_bonsai_lab_token: str | None = Header(default=None),
    x_bonsai_worker_id: str | None = Header(default=None),
) -> str:
    _require(get_settings().lab_token, x_bonsai_lab_token, "lab")
    worker_id = x_bonsai_worker_id or "bonsai-lab-agent"
    if not WORKER_ID_PATTERN.fullmatch(worker_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid worker id",
        )
    return worker_id


def require_admin(x_bonsai_admin_token: str | None = Header(default=None)) -> str:
    _require(get_settings().admin_token, x_bonsai_admin_token, "admin")
    return "admin"
