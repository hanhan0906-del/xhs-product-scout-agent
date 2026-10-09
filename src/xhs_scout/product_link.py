from __future__ import annotations

import html
import re
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, unquote, urlsplit
from urllib.request import Request, urlopen

from .emulator import AdbDevice
from .ui_automation import (
    find_copy_link_button,
    find_share_product_button,
    product_detail_controls_present,
)


URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
SHORT_PRODUCT_PATH_RE = re.compile(r"/(?:a|m)/[A-Za-z0-9_-]+/?")
DIRECT_PRODUCT_PATH_RE = re.compile(r"/(?:goods|goods-detail)/[A-Za-z0-9_-]+/?")
DEEPLINK_PRODUCT_PATH_RE = re.compile(r"/goods/[A-Za-z0-9_-]+/?")
DIRECT_PRODUCT_URL_RE = re.compile(
    r"https://(?:www\.)?xiaohongshu\.com/"
    r"(?:goods|goods-detail)/[A-Za-z0-9_-]+(?:\?[^\s<>\"']*)?",
    re.IGNORECASE,
)
DEEPLINK_PRODUCT_URL_RE = re.compile(
    r"xhsdiscover://(?:page/goods|goods_detail)/[A-Za-z0-9_-]+"
    r"(?:\?[^\s<>\"'}]*)?",
    re.IGNORECASE,
)
MAX_RESOLUTION_BODY_BYTES = 256 * 1024


def is_supported_product_url(value: str | None) -> bool:
    if not value:
        return False
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme.casefold() != "https"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port is not None
        ):
            return False
    except ValueError:
        return False

    host = (parsed.hostname or "").rstrip(".").casefold()
    if host == "xhslink.com":
        return SHORT_PRODUCT_PATH_RE.fullmatch(parsed.path) is not None
    if host in {"xiaohongshu.com", "www.xiaohongshu.com"}:
        return DIRECT_PRODUCT_PATH_RE.fullmatch(parsed.path) is not None
    return False


def is_supported_product_direct_url(value: str | None) -> bool:
    """Accept only durable, identity-bearing product targets.

    Public xhslink short URLs are deliberately excluded. They remain useful as
    operator-facing share links but can expire and therefore cannot be frozen
    into a daily-sales plan.
    """
    if not value:
        return False
    try:
        parsed = urlsplit(value)
        if (
            parsed.username is not None
            or parsed.password is not None
            or parsed.port is not None
        ):
            return False
    except ValueError:
        return False

    scheme = parsed.scheme.casefold()
    host = (parsed.hostname or "").rstrip(".").casefold()
    if scheme == "https" and host in {"xiaohongshu.com", "www.xiaohongshu.com"}:
        return DIRECT_PRODUCT_PATH_RE.fullmatch(parsed.path) is not None
    if scheme != "xhsdiscover":
        return False
    if host == "page":
        return DEEPLINK_PRODUCT_PATH_RE.fullmatch(parsed.path) is not None
    return (
        host == "goods_detail"
        and re.fullmatch(r"/[A-Za-z0-9_-]+/?", parsed.path) is not None
    )


def extract_product_direct_url(value: str | None) -> str | None:
    searchable = unquote(html.unescape(value or "")).replace("\\/", "/")
    for pattern in (DIRECT_PRODUCT_URL_RE, DEEPLINK_PRODUCT_URL_RE):
        for match in pattern.finditer(searchable):
            candidate = match.group(0).rstrip("。；，、！？,.);]}")
            if is_supported_product_direct_url(candidate):
                parsed = urlsplit(candidate)
                if parsed.scheme.casefold() == "xhsdiscover":
                    return f"xhsdiscover://{parsed.netloc}{parsed.path}".rstrip("/")
                return candidate
    return None


def _embedded_instation_direct_url(value: str | None) -> str | None:
    try:
        query = parse_qs(urlsplit(value or "").query)
    except ValueError:
        return None
    for item in query.get("instation_link", []):
        candidate = extract_product_direct_url(item)
        if candidate and candidate.startswith("xhsdiscover://"):
            return candidate
    return None


def resolve_product_direct_url(
    value: str | None,
    *,
    opener=None,
    timeout_seconds: float = 8.0,
) -> dict:
    """Resolve a public share link to a durable official product target.

    Resolution follows only the public HTTPS share URL. The returned target is
    accepted only when it is an official Xiaohongshu product URL or the
    documented ``xhsdiscover://page/goods/<id>`` deeplink.
    """
    if is_supported_product_direct_url(value):
        return {
            "direct_url": str(value).strip(),
            "resolution": "already_direct",
            "skip_reason": None,
        }
    if not is_supported_product_url(value):
        return {
            "direct_url": None,
            "resolution": "rejected",
            "skip_reason": "share link is not a supported Xiaohongshu product URL",
        }

    request = Request(
        str(value).strip(),
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    open_request = opener or urlopen
    try:
        response = open_request(request, timeout=max(0.5, float(timeout_seconds)))
        with response:
            final_url = str(response.geturl() or "")
            body = response.read(MAX_RESOLUTION_BODY_BYTES + 1)
    except HTTPError as error:
        final_url = str(error.geturl() or "")
        embedded_direct_url = _embedded_instation_direct_url(final_url)
        if embedded_direct_url:
            return {
                "direct_url": embedded_direct_url,
                "resolution": "public_redirect_deeplink",
                "skip_reason": None,
            }
        if is_supported_product_direct_url(final_url):
            return {
                "direct_url": final_url,
                "resolution": "public_redirect",
                "skip_reason": None,
            }
        return {
            "direct_url": None,
            "resolution": "unavailable",
            "skip_reason": f"share link resolution failed: {type(error).__name__}",
        }
    except (URLError, TimeoutError, OSError, ValueError) as error:
        return {
            "direct_url": None,
            "resolution": "unavailable",
            "skip_reason": f"share link resolution failed: {type(error).__name__}",
        }

    embedded_direct_url = _embedded_instation_direct_url(final_url)
    if embedded_direct_url:
        return {
            "direct_url": embedded_direct_url,
            "resolution": "public_redirect_deeplink",
            "skip_reason": None,
        }
    if is_supported_product_direct_url(final_url):
        return {
            "direct_url": final_url,
            "resolution": "public_redirect",
            "skip_reason": None,
        }
    if len(body) > MAX_RESOLUTION_BODY_BYTES:
        return {
            "direct_url": None,
            "resolution": "rejected",
            "skip_reason": "share link resolution response was too large",
        }

    decoded = body.decode("utf-8", errors="replace")
    candidate = extract_product_direct_url(decoded)
    if candidate:
        return {
            "direct_url": candidate,
            "resolution": "public_page",
            "skip_reason": None,
        }
    return {
        "direct_url": None,
        "resolution": "unresolved",
        "skip_reason": "share link did not expose a verified product target",
    }


def _product_identity(value: str | None) -> str | None:
    if not is_supported_product_direct_url(value):
        return None
    parsed = urlsplit(str(value))
    parts = [part for part in parsed.path.split("/") if part]
    if parsed.scheme.casefold() == "https":
        return parts[-1] if parts else None
    if parsed.hostname == "goods_detail":
        return parts[0] if parts else None
    if parsed.hostname == "page" and len(parts) == 2 and parts[0] == "goods":
        return parts[1]
    return None


def resolve_product_launch_url(
    share_url: str | None,
    verified_direct_url: str | None,
    *,
    opener=None,
    timeout_seconds: float = 8.0,
) -> dict:
    """Resolve a fresh public launch URL while preserving frozen identity.

    The durable URL remains the identity anchor. For an xhslink share URL we
    follow its public redirect on each run and only accept the official
    goods-detail URL when its product id matches the frozen anchor.
    """
    expected_identity = _product_identity(verified_direct_url)
    if expected_identity is None:
        return {
            "launch_url": None,
            "resolution": "rejected",
            "skip_reason": "verified product identity is unavailable",
        }

    try:
        parsed_share = urlsplit(share_url or "")
    except ValueError:
        parsed_share = None
    if (
        parsed_share is None
        or parsed_share.scheme.casefold() != "https"
        or (parsed_share.hostname or "").rstrip(".").casefold() != "xhslink.com"
        or not is_supported_product_url(share_url)
    ):
        return {
            "launch_url": str(verified_direct_url).strip(),
            "resolution": "verified_direct",
            "skip_reason": None,
        }

    request = Request(
        str(share_url).strip(),
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    open_request = opener or urlopen
    try:
        response = open_request(request, timeout=max(0.5, float(timeout_seconds)))
        with response:
            final_url = str(response.geturl() or "")
    except HTTPError as error:
        final_url = str(error.geturl() or "")
    except (URLError, TimeoutError, OSError, ValueError) as error:
        return {
            "launch_url": None,
            "resolution": "unavailable",
            "skip_reason": f"share launch resolution failed: {type(error).__name__}",
        }

    actual_identity = _product_identity(final_url)
    if actual_identity != expected_identity:
        return {
            "launch_url": None,
            "resolution": "identity_mismatch",
            "skip_reason": "public share redirect does not match frozen product identity",
        }
    return {
        "launch_url": final_url,
        "resolution": "fresh_public_redirect",
        "skip_reason": None,
    }


def extract_share_url(value: str | None) -> str | None:
    for match in URL_RE.finditer(value or ""):
        candidate = match.group(0).rstrip("。；，、！？,.);]}")
        if is_supported_product_url(candidate):
            return candidate
    return None


def capture_product_share_url(
    device: AdbDevice,
    *,
    wait_seconds: float = 1.5,
    clipboard_timeout_seconds: float = 5.0,
) -> dict:
    activity_direct_url = None
    activity_dump = getattr(device, "activity_dump", None)
    if callable(activity_dump):
        try:
            activity_direct_url = extract_product_direct_url(activity_dump())
        except Exception:
            activity_direct_url = None

    if activity_direct_url and is_supported_product_direct_url(activity_direct_url):
        return {
            "share_url": None,
            "direct_url": activity_direct_url,
            "direct_url_resolution": "visible_activity_intent",
            "direct_url_gap": None,
            "skip_reason": None,
        }

    def direct_url_fallback(skip_reason: str) -> dict:
        result = {"share_url": None, "skip_reason": skip_reason}
        if activity_direct_url:
            result.update(
                {
                    "direct_url": activity_direct_url,
                    "direct_url_resolution": "visible_activity_intent",
                    "direct_url_gap": skip_reason,
                }
            )
        return result

    before_xml = device.ui_dump()
    share_target = find_share_product_button(before_xml)
    if not share_target:
        return direct_url_fallback("share product button not found")

    original_clipboard = device.get_windows_clipboard()
    original_url = extract_share_url(original_clipboard)
    marker = f"xhs-scout-link-{uuid.uuid4().hex}"
    share_sheet_open = False
    try:
        device.set_windows_clipboard(marker)
        device.tap(share_target.x, share_target.y)
        share_sheet_open = True
        time.sleep(wait_seconds)
        share_xml = device.ui_dump()
        copy_target = find_copy_link_button(share_xml)
        if not copy_target:
            return direct_url_fallback("copy link button not found")

        device.tap(copy_target.x, copy_target.y)
        deadline = time.monotonic() + clipboard_timeout_seconds
        saw_unchanged_url = False
        saw_invalid_url = False
        while time.monotonic() < deadline:
            time.sleep(0.5)
            clipboard_text = device.get_windows_clipboard()
            share_url = extract_share_url(clipboard_text)
            if share_url and share_url == original_url:
                saw_unchanged_url = True
                continue
            if share_url:
                resolved = (
                    {
                        "direct_url": activity_direct_url,
                        "resolution": "visible_activity_intent",
                        "skip_reason": None,
                    }
                    if activity_direct_url
                    else resolve_product_direct_url(share_url)
                )
                return {
                    "share_url": share_url,
                    "direct_url": resolved["direct_url"],
                    "direct_url_resolution": resolved["resolution"],
                    "direct_url_gap": resolved["skip_reason"],
                    "share_target": share_target.label,
                    "copy_target": copy_target.label,
                }
            if URL_RE.search(clipboard_text or ""):
                saw_invalid_url = True
        if saw_unchanged_url:
            skip_reason = "clipboard still contains the previous product URL"
        elif saw_invalid_url:
            skip_reason = "copied clipboard does not contain a supported Xiaohongshu product URL"
        else:
            skip_reason = "copied link did not reach Windows clipboard"
        return direct_url_fallback(skip_reason)
    finally:
        if share_sheet_open:
            try:
                current_xml = device.ui_dump()
                if not product_detail_controls_present(current_xml):
                    device.back()
                    time.sleep(0.5)
            except Exception:
                pass
        device.set_windows_clipboard(original_clipboard)
