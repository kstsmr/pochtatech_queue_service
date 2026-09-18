from io import BytesIO
from urllib.parse import urlencode, urlsplit, urlunsplit

import segno

from app.core.config import settings


def public_client_origin(override: str | None = None) -> str:
    """Return a validated origin; local demos may override it for phone testing."""
    candidate = override if override and settings.app_env in {"development", "test"} else str(settings.public_client_url)
    parts = urlsplit(candidate.strip())
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or parts.path not in {"", "/"}
    ):
        raise ValueError("public client origin must be an HTTP(S) origin without path or credentials")
    return urlunsplit((parts.scheme, parts.netloc, "", "", "")).rstrip("/")


def branch_join_url(postal_code: str, public_origin: str | None = None) -> str:
    """Build a stable deep-link containing only the public branch code."""
    base = public_client_origin(public_origin)
    parts = urlsplit(f"{base}/qr")
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode({"branch": postal_code}), ""))


def branch_qr_svg(postal_code: str, public_origin: str | None = None) -> bytes:
    output = BytesIO()
    qr = segno.make(branch_join_url(postal_code, public_origin), error="m", micro=False)
    qr.save(
        output,
        kind="svg",
        scale=8,
        border=4,
        dark="#15243a",
        light="#ffffff",
        xmldecl=False,
        svgns=True,
        title=f"Очередь отделения {postal_code}",
        desc="QR-код для входа в электронную очередь",
    )
    return output.getvalue()
