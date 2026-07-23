"""Strict support for verified zero-result LAMOST Gaia form batches.

The live zero-result contract is: the exact first-party action returns HTTP 200,
``Content-Disposition`` is present, and the response body is exactly zero bytes.
Only that signature is converted into an empty table with the frozen live header.
Arbitrary empty responses, HTML pages, redirects, and transport errors remain fatal.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request

from hou_compact import lamost_gaia_form_rv as base
from hou_compact import lamost_gaia_form_rv_v2 as sessioned

# Frozen by the successful public exact-sample and zero-result contracts.
_ZERO_RESULT_COLUMNS = (
    "obsid",
    "obsdate",
    "lmjd",
    "mjd",
    "snrg",
    "snri",
    "class",
    "subclass",
    "ra",
    "dec",
    "fibermask",
    "gaia_source_id",
    "rv_err",
    "rv",
)
_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def _open_with_disposition(
    opener: Any,
    request: Request,
    *,
    timeout: float,
    maximum_bytes: int,
) -> tuple[int, str, str, str, bytes]:
    try:
        with opener.open(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 200))
            final_url = str(getattr(response, "geturl", lambda: request.full_url)())
            content_type = str(response.headers.get("Content-Type", ""))
            disposition = str(response.headers.get("Content-Disposition", ""))
            raw = base._bounded_read(response, maximum_bytes)
    except HTTPError as error:
        raise base.LamostGaiaFormError(
            f"LAMOST Gaia form returned HTTP {error.code}"
        ) from error
    except URLError as error:
        raise base.LamostGaiaFormError(
            f"LAMOST Gaia form transport failed: {error.reason}"
        ) from error
    if status != 200:
        raise base.LamostGaiaFormError(f"LAMOST Gaia form returned HTTP {status}")
    return status, final_url, content_type, disposition, raw


def _same_action_path(first: str, second: str) -> bool:
    a = urlparse(first)
    b = urlparse(second)
    return (
        a.scheme == b.scheme == "https"
        and a.netloc == b.netloc
        and a.path.rstrip("/") == b.path.rstrip("/")
    )


def _fetch_batch_zero_aware(
    opener: Any,
    *,
    action_url: str,
    referer_url: str,
    dr2_ids: tuple[str, ...],
    output_columns: tuple[str, ...],
    collection: str,
    timeout: float,
    maximum_response_bytes: int,
) -> tuple[base.ParsedTable, list[dict[str, object]]]:
    boundary = "----HOUCOMPACT" + secrets.token_hex(16)
    fields: list[tuple[str, str]] = [
        ("sForm", "0"),
        ("pos.type", "none"),
        ("gaiasourcearea", "\n".join(dr2_ids)),
        ("output.collection", collection),
        ("output.fmt", "csv"),
    ]
    fields.extend((f"output.combined.{column}", "on") for column in output_columns)
    fields.append(("sBtn", "Search"))
    body = base._multipart_body(fields, boundary)
    parsed_action = urlparse(action_url)
    origin = f"{parsed_action.scheme}://{parsed_action.netloc}"
    request = Request(
        action_url,
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
            "User-Agent": "HOU-COMPACT/1.0 exact Gaia DR2 LAMOST form client",
            "Accept": "text/csv,text/plain,text/html,*/*;q=0.1",
            "Accept-Encoding": "identity",
            "Origin": origin,
            "Referer": referer_url,
        },
        method="POST",
    )
    status, final_url, content_type, disposition, raw = _open_with_disposition(
        opener,
        request,
        timeout=timeout,
        maximum_bytes=maximum_response_bytes,
    )
    zero_attachment = bool(
        status == 200
        and not raw
        and disposition.strip()
        and _same_action_path(final_url, action_url)
    )
    receipts: list[dict[str, object]] = [
        {
            "kind": "form_post",
            "http_status": status,
            "content_type": content_type,
            "content_disposition_present": bool(disposition.strip()),
            "response_bytes": len(raw),
            "response_sha256": hashlib.sha256(raw).hexdigest(),
            "final_url_path": base._safe_path(final_url),
            "verified_zero_result_attachment": zero_attachment,
        }
    ]
    if zero_attachment:
        return (
            base.ParsedTable(
                delimiter="|",
                columns=_ZERO_RESULT_COLUMNS,
                rows=(),
                response_sha256=_EMPTY_SHA256,
                response_bytes=0,
                source_kind="form_post_empty_attachment",
                source_url_path=base._safe_path(final_url),
            ),
            receipts,
        )
    if not raw:
        raise base.LamostGaiaFormError(
            "LAMOST Gaia form returned an empty response without the verified attachment contract"
        )

    direct = base._parse_response(raw, source_kind="form_post", source_url=final_url)
    if direct is not None:
        return direct, receipts
    for link in base._same_origin_followups(raw, base_url=final_url):
        follow_request = Request(
            link,
            headers={
                "User-Agent": "HOU-COMPACT/1.0 exact Gaia DR2 LAMOST form client",
                "Accept": "text/csv,text/plain,*/*;q=0.1",
                "Accept-Encoding": "identity",
                "Referer": final_url,
            },
        )
        follow_status, follow_url, follow_type, follow_disposition, follow_raw = (
            _open_with_disposition(
                opener,
                follow_request,
                timeout=timeout,
                maximum_bytes=maximum_response_bytes,
            )
        )
        receipts.append(
            {
                "kind": "same_origin_followup",
                "http_status": follow_status,
                "content_type": follow_type,
                "content_disposition_present": bool(follow_disposition.strip()),
                "response_bytes": len(follow_raw),
                "response_sha256": hashlib.sha256(follow_raw).hexdigest(),
                "final_url_path": base._safe_path(follow_url),
                "verified_zero_result_attachment": False,
            }
        )
        parsed = base._parse_response(
            follow_raw,
            source_kind="same_origin_followup",
            source_url=follow_url,
        )
        if parsed is not None:
            return parsed, receipts
    raise base.LamostGaiaFormError(
        "LAMOST Gaia form exposed no bounded delimited result"
    )


def acquire_gaia_form_rv_sessioned_zero_aware(**kwargs: Any) -> dict[str, object]:
    """Run fresh-session acquisition with the exact empty-attachment contract."""

    previous = base._fetch_batch
    base._fetch_batch = _fetch_batch_zero_aware
    try:
        return sessioned.acquire_gaia_form_rv_sessioned(**kwargs)
    finally:
        base._fetch_batch = previous
