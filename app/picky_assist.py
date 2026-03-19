import os
import httpx
import re
from typing import List, Optional, Dict, Any

# Picky Assist V2 Push API Base URL
PICKY_ASSIST_BASE_URL = "https://pickyassist.com/app/api/v2/push"


class PickyAssistError(Exception):
    pass


def normalise_phone(phone: str) -> Optional[str]:
    """
    Format phone to E.164 and then remove '+' as Picky Assist handles numeric strings.
    E.g. +91 9876543210 -> 919876543210
    """
    if not phone:
        return None
    cleaned = re.sub(r"[^\d+]", "", phone)
    if cleaned.startswith("+"):
        return cleaned[1:]
    if len(cleaned) == 10:
        return f"91{cleaned}"  # Assuming Indian numbers if 10 digits
    return cleaned


async def send_picky_assist_message(
    template_id: str,
    recipients: List[Dict[str, Any]],
    application_id: Optional[int] = None,
    token: Optional[str] = None,
    global_media: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Sends messages via Picky Assist Push API (V2).
    Supported single and bulk via the 'data' array.
    """
    # Fallback to environment variables if not provided
    token = token or os.environ.get("PICKY_ASSIST_TOKEN", "")
    app_id = application_id or int(os.environ.get("PICKY_ASSIST_APPLICATION_ID", "8"))

    if not token:
        return {"success": False, "error": "PICKY_ASSIST_TOKEN is missing."}

    # Construct Picky Assist payload
    data_list = []
    for rec in recipients:
        phone = normalise_phone(rec.get("number") or rec.get("phone"))
        if not phone:
            continue

        entry = {
            "number": phone,
            "template_message": rec.get("template_message")
            or rec.get("template_params")
            or [],
            "language": rec.get("language", "en"),
        }

        # Per-recipient media (header image)
        media_val = rec.get("media")
        if media_val:
            if isinstance(media_val, dict):
                # Dict match common payload: {"url": "...", "filename": "..."}
                entry["media"] = str(media_val.get("url") or "")
            elif hasattr(media_val, 'url'):
                # Handle Pydantic model if passed
                entry["media"] = str(media_val.url)
            else:
                # String URL
                entry["media"] = str(media_val)

        data_list.append(entry)

    if not data_list:
        return {
            "success": False,
            "error": "No valid recipients found after normalization.",
        }

    payload = {
        "token": token,
        "application": app_id,
        "template_id": template_id,
        "data": data_list,
    }

    # Global media can be passed if all recipients use the same image,
    # but the API allows it per-recipient in the 'data' array as well.
    if global_media:
        payload["globalmedia"] = global_media

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(PICKY_ASSIST_BASE_URL, json=payload, timeout=15.0)

        result = resp.json()

        # Picky Assist V2 response usually has "status" or "code"
        # 100 is typically success for Picky Assist, let's check documentation specifics
        # If it returns success: True or status: 100
        if resp.status_code == 200:
            # Picky Assist status can be string or int
            status = result.get("status") or result.get("code")
            if str(status) in ["100", "success", "True", "true"]:
                return {"success": True, "data": result}
            else:
                return {
                    "success": False,
                    "error": result.get("message") or f"Picky Assist Status: {status}",
                }
        else:
            return {
                "success": False,
                "error": f"HTTP Error {resp.status_code}: {resp.text}",
            }

    except Exception as e:
        return {"success": False, "error": f"Exception calling Picky Assist: {e}"}
