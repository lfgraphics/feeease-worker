import os
import asyncio
import httpx
from datetime import datetime
from bson import ObjectId
from app.db import get_school_db
from app.crypto import safe_decrypt

WEBHOOK_SECRET = os.environ.get("WORKER_WEBHOOK_SECRET", "")
MAX_ATTEMPTS = 3
BASE_DELAY_MS = 2000

async def deliver_webhook(school_id: str, webhook_url: str, job_id: str, summary: dict, mongo_uri: str):
    """
    Attempts to deliver the final broadcast summary to the school's webhook URL.
    Uses exponential backoff for retries.
    If all webhook delivery attempts fail, it connects directly to the school's MongoDB
    and updates the WhatsAppStat record to prevent stuck "pending" statuses.
    """
    payload = {
        "jobId": job_id,
        "schoolId": school_id,
        "status": "completed",
        "result": summary
    }
    
    webhook_secret = os.environ.get("WORKER_WEBHOOK_SECRET", "")
    
    headers = {
        "Content-Type": "application/json",
        "X-Worker-Secret": webhook_secret
    }
    
    async with httpx.AsyncClient() as client:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                resp = await client.post(webhook_url, json=payload, headers=headers, timeout=10.0)
                if resp.status_code in (200, 201, 204):
                    print(f"[Webhook Success] Delivery to {webhook_url} succeeded (attempt {attempt}).")
                    return True
                else:
                    print(f"[Webhook Warn] Delivery to {webhook_url} got status {resp.status_code} (attempt {attempt})")
            except Exception as e:
                print(f"[Webhook Warn] Delivery to {webhook_url} failed with exception {type(e).__name__} (attempt {attempt})")

            # Final attempt failed
            if attempt == MAX_ATTEMPTS:
                print(f"[Webhook Error] Delivery to {webhook_url} permanently failed after {MAX_ATTEMPTS} attempts.")
                break
                
            # Exponential backoff: 2s, 4s
            await asyncio.sleep((BASE_DELAY_MS * (2 ** (attempt - 1))) / 1000.0)

    # -------------------------------------------------------------------------------------
    # DB Fallback: The school app isn't responding or webhook died. We forcefully update
    # the WhatsAppStat in its DB so it doesn't stay "pending" forever.
    # -------------------------------------------------------------------------------------
    print(f"[Webhook Fallback] Connecting directly to school DB to update stat {job_id}...")
    
    try:
        decrypted_uri = safe_decrypt(mongo_uri)
        db, db_client = await get_school_db(decrypted_uri)
        
        # Calculate derived status
        total_recipients = len(summary.get("results", []))
        success_count = summary.get("success", 0)
        
        computed_status = "failed"
        if success_count > 0:
            computed_status = "success" if success_count == total_recipients else "partial"
            
        now = datetime.utcnow()
        
        result = await db.whatsappstats.update_one(
            {"batchId": job_id},
            {"$set": {
                "status": computed_status,
                "sentCount": summary.get("success", 0),
                "failedCount": summary.get("failed", 0),
                "skippedCount": summary.get("skipped", 0),
                "completedAt": now,
                "workerDetails": summary.get("results", [])
            }}
        )
        
        # Close connection immediately since we created it epshemerally
        db_client.close()
        
        if result.modified_count > 0:
            print(f"[Webhook Fallback Success] Force-updated WhatsAppStat for {job_id} in school DB.")
            return True
        else:
            print(f"[Webhook Fallback Warn] WhatsAppStat matched 0 docs for batchId {job_id}.")
            return False
            
    except Exception as fallback_err:
        print(f"[Webhook Fallback Error] Critical failure writing to school DB directly: {fallback_err}")
        return False
