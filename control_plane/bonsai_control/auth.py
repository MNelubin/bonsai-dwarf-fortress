import secrets

from fastapi import Header, HTTPException, status

from .settings import get_settings


def _require(expected: str, supplied: str | None, label: str) -> None:
    if supplied is None or not secrets.compare_digest(expected, supplied):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"invalid {label} token")


def require_lab(x_bonsai_lab_token: str | None = Header(default=None)) -> str:
    _require(get_settings().lab_token, x_bonsai_lab_token, "lab")
    return "bonsai-lab"


def require_admin(x_bonsai_admin_token: str | None = Header(default=None)) -> str:
    _require(get_settings().admin_token, x_bonsai_admin_token, "admin")
    return "admin"

