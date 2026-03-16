import os
import httpx
import re
from typing import List, Optional, Dict, Any

# Delay is managed in the broadcast processor, so here we just handle the single API call

AISENSY_BASE_URL = os.environ.get("AISENSY_BASE_URL", "https://backend.aisensy.com/campaign/t1/api/v2")

class AiSensyError(Exception):
    pass

def normalise_phone(phone: str) -> Optional[str]:
    """
    Format phone to E.164 without the '+'
    E.g. +91 9876543210 -> 919876543210
    """
    if not phone:
        return None
    cleaned = re.sub(r"[^\d+]", "", phone)
    
    # Needs to match pattern: ^(|\\+?91)\\d{10}$ (or similar, assuming prepends if local)
    if cleaned.startswith("+"):
        return cleaned[1:]
    if len(cleaned) == 10:
        return f"91{cleaned}"  # Default mapping for Indian 10-digit numbers
        
    return cleaned

async def send_aisensy_message(
    campaign_name: str,
    destination: str,
    user_name: str,
    source: str,
    template_params: List[str] = None,
    media: Optional[Dict[str, str]] = None,
    tags: Optional[List[str]] = None,
    attributes: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    
    api_key = os.environ.get("AISENSY_API_KEY", "")
    if not api_key:
        return {"success": False, "error": "AISENSY_API_KEY is missing entirely on worker."}

    norm_dest = normalise_phone(destination)
    if not norm_dest:
        return {"success": False, "error": "Invalid phone formatting"}

    payload = {
        "apiKey": api_key,
        "campaignName": campaign_name,
        "destination": norm_dest,
        "userName": user_name,
        "source": source
    }
    
    if media:
        payload["media"] = media
    if template_params:
        payload["templateParams"] = template_params
    if tags:
        payload["tags"] = tags
    if attributes:
        payload["attributes"] = attributes

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(AISENSY_BASE_URL, json=payload, timeout=10.0)
            
        data = resp.json()
        
        is_success = str(data.get("success", "false")).lower() == "true"
        
        if resp.status_code in (200, 201, 202) and is_success:
            msg_id = data.get("messageId") or data.get("submitted_message_id") or "sent"
            return {"success": True, "messageId": msg_id}
        else:
            return {"success": False, "error": data.get("error") or data.get("message") or resp.text}
    except Exception as e:
        return {"success": False, "error": f"Exception thrown calling AiSensy: {e}"}
