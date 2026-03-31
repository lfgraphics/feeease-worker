import json
import logging
import asyncio
import os
from pywebpush import webpush, WebPushException

logger = logging.getLogger(__name__)

# Use standard os.getenv for keys
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY")
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY")
VAPID_CLAIMS = {
    "sub": os.getenv("VAPID_SUB", "mailto:admin@modern-nursery.com")
}

# Semaphore to prevent overwhelming the server or hitting rate limits
# Allows 50 concurrent push requests
PUSH_SEMAPHORE = asyncio.Semaphore(50)

def send_push_notification_sync(subscription_json: str, data: dict):
    """
    Internal synchronous wrapper for pywebpush.
    """
    if not VAPID_PRIVATE_KEY or not VAPID_PUBLIC_KEY:
        logger.error("VAPID keys not configured in environment.")
        return False

    try:
        subscription_info = json.loads(subscription_json)
        
        webpush(
            subscription_info=subscription_info,
            data=json.dumps(data),
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims=VAPID_CLAIMS
        )
        return True
    except WebPushException as ex:
        logger.error(f"WebPush error: {ex}")
        return False
    except Exception as e:
        logger.error(f"Unexpected push error: {e}")
        return False

async def send_push_async(subscription_json: str, data: dict):
    """Async wrapper using semaphore to limit concurrency."""
    async with PUSH_SEMAPHORE:
        # Run the sync webpush call in a separate thread to keep the event loop free
        return await asyncio.to_thread(send_push_notification_sync, subscription_json, data)

async def broadcast_push_notifications(push_targets: list, data: dict):
    """
    Optimized for bulk delivery (e.g. 1000+ notifications) using concurrency.
    push_targets: List of objects with studentId/teacherId and tokens[]
    data: Dictionary containing title, body, icon, etc.
    """
    tasks = []
    for target in push_targets:
        tokens = target.get("tokens", [])
        for token_json in tokens:
            tasks.append(send_push_async(token_json, data))

    if not tasks:
        return []

    logger.info(f"Starting async broadcast of {len(tasks)} push notifications...")
    
    # asyncio.gather will wait for all tasks to complete and return their results
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Process results slightly to count success/failure
    serialized_results = []
    success_count = 0
    for idx, res in enumerate(results):
        if isinstance(res, Exception):
            logger.error(f"Push task error in index {idx}: {res}")
            serialized_results.append(False)
        else:
            if res:
              success_count += 1
            serialized_results.append(res)
            
    logger.info(f"Broadcast complete: {success_count}/{len(tasks)} notifications delivered successfully.")
    return serialized_results
