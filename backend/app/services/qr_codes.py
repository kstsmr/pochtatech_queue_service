from io import BytesIO
from urllib.parse import urlencode, urlsplit, urlunsplit

import segno

from app.core.config import settings


def branch_join_url(postal_code: str) -> str:
    """Build a stable deep-link containing only the public branch code."""
    base = str(settings.public_client_url).rstrip("/")
    parts = urlsplit(f"{base}/qr")
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode({"branch": postal_code}), ""))


def branch_qr_svg(postal_code: str) -> bytes:
    output = BytesIO()
    qr = segno.make(branch_join_url(postal_code), error="m", micro=False)
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
