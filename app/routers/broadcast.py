from fastapi import APIRouter, HTTPException, BackgroundTasks, Header
from pydantic import BaseModel, HttpUrl
from typing import List, Optional, Dict, Any
from bson import ObjectId
from app.db import connect_feeease
from app.aisensy import send_aisensy_message
from app.webhook import deliver_webhook
from app.config import settings
import asyncio
import uuid
import re
from datetime import datetime
import os
from app.push_utils import broadcast_push_notifications

router = APIRouter()


# -------------------------------------------------------------------------
# Shared Models
# -------------------------------------------------------------------------
class MediaModel(BaseModel):
    url: HttpUrl
    filename: str

class TextRecipientModel(BaseModel):
    phone: str
    studentName: str
    parentName: str

class ReminderRecipientModel(BaseModel):
    phone: str
    studentName: str
    parentName: str
    dueAmount: str
    dueDate: Optional[str] = None
    month: Optional[str] = None

class NotificationRequest(BaseModel):
    schoolId: str
    licenseKey: str
    mode: str = "bulk"
    webhookUrl: HttpUrl
    jobId: Optional[str] = None
    source: Optional[str] = None
    notificationType: str
    mainMessage: str
    recipients: List[TextRecipientModel]
    media: Optional[MediaModel] = None
    pushTargets: Optional[List[Dict[str, Any]]] = None


class ReminderRequest(BaseModel):
    schoolId: str
    licenseKey: str
    mode: str = "bulk"
    language: str = "english"
    webhookUrl: HttpUrl
    jobId: Optional[str] = None
    source: Optional[str] = None
    recipients: List[ReminderRecipientModel]
    pushTargets: Optional[List[Dict[str, Any]]] = None

class AppNotificationRequest(BaseModel):
    schoolId: str
    licenseKey: str
    title: str
    body: str
    icon: Optional[str] = "/logo.jpeg"
    pushTargets: List[Dict[str, Any]]



class ReceiptRequest(BaseModel):
    schoolId: str
    licenseKey: str
    mode: str = "single"
    source: Optional[str] = None
    phone: str
    parentName: str
    studentName: str
    amount: str
    receiptNumber: str
    month: Optional[str] = None
    media: Optional[MediaModel] = None

class OtpRequest(BaseModel):
    schoolId: str
    licenseKey: str
    phone: str
    userName: str
    otp: str
    role: Optional[str] = "user"
    schoolName: Optional[str] = None
    validity: str = "5 minutes"
    source: Optional[str] = None


class SystemOtpRequest(BaseModel):
    phone: str
    userName: str
    otp: str
    role: Optional[str] = "admin"
    schoolName: Optional[str] = "FeeEase"
    source: Optional[str] = "FeeEase System"


# -------------------------------------------------------------------------
# Utilities
# -------------------------------------------------------------------------
def sanitize_param(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\t", " ")
    text = re.sub(r'[\n\r]+', ' ', text)
    text = re.sub(r' {4,}', '   ', text)
    return text.strip()


def validate_webhook_secret(authorization: str):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401, detail="Missing or invalid Authorization header"
        )
    token = authorization.split(" ")[1]
    if token != settings.WORKER_WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Invalid webhook secret")


async def validate_auth_limits(db, school_id: str, license_key: str, cost: int):
    try:
        school = await db.schools.find_one({"_id": ObjectId(school_id)})
    except:
        raise HTTPException(status_code=400, detail="Invalid school ID format")
        
    if not school:
        raise HTTPException(status_code=404, detail="School not found in centralized datastore")
        
    d_license = school.get("license", {})
    if d_license.get("licenseKey") != license_key:
        raise HTTPException(status_code=403, detail="Invalid license key provided")
        
    features = school.get("features", {})
    if not features.get("whatsapp"):
        raise HTTPException(status_code=403, detail="WhatsApp integration is not enabled for this school's plan")

    usage = school.get("whatsappUsage", {})
    soft_limit = usage.get("softLimit", 5000)
    month_year = usage.get("monthYear", "")
    
    now = datetime.utcnow()
    current_month_year = f"{now.year}-{str(now.month).zfill(2)}"
    
    sent_this_month = usage.get("sentThisMonth", 0) if month_year == current_month_year else 0
    
    if soft_limit > 0 and (sent_this_month + cost) > soft_limit:
        raise HTTPException(
            status_code=402,
            detail=f"Refusal to broadcast: School hit its soft limit of {soft_limit} messages/month. Cannot send {cost} more.",
        )
    return school, school.get("name", "Unknown School")

async def update_usage_counter(db, school_id: str, success_count: int):
    if success_count == 0:
        return
    now = datetime.utcnow()
    month_year = f"{now.year}-{str(now.month).zfill(2)}"
    try:
        res = await db.schools.update_one(
            {"_id": ObjectId(school_id), "whatsappUsage.monthYear": month_year},
            {"$inc": {"whatsappUsage.sentThisMonth": success_count}}
        )
        if res.modified_count == 0:
            school = await db.schools.find_one({"_id": ObjectId(school_id)})
            if school:
                old_usage = school.get("whatsappUsage", {})
                await db.schools.update_one(
                    {"_id": ObjectId(school_id)},
                    {"$set": {
                        "whatsappUsage": {
                            "monthYear": month_year,
                            "sentThisMonth": success_count,
                            "softLimit": old_usage.get("softLimit", 5000)
                        }
                    }}
                )
    except Exception as e:
        print(f"[Worker Error] Usage sync failed: {e}")

# -------------------------------------------------------------------------
# Processors
# -------------------------------------------------------------------------
async def process_notification_job(payload: NotificationRequest, school: dict, job_id: str, is_image: bool = False):
    template_id = settings.AISENSY_TEMPLATES["universal_image"] if is_image else settings.AISENSY_TEMPLATES["universal_text"]
    school_name = school.get("name", "Unknown School")
    base_source = payload.source or f"FeeEase - {school_name}"
    
    success_count = failed_count = skipped_count = 0
    results = []

    notif_type = sanitize_param(payload.notificationType)
    main_msg = sanitize_param(payload.mainMessage)

    for rec in payload.recipients:
        if not rec.phone:
            skipped_count += 1
            results.append({"phone": "Unknown", "status": "skipped", "error": "No phone number", "id": rec.studentName})
            continue

        template_params = [
            sanitize_param(rec.parentName),
            notif_type,
            sanitize_param(school_name),
            sanitize_param(rec.studentName),
            main_msg
        ]

        media_dict = {"url": str(payload.media.url), "filename": payload.media.filename} if payload.media else None

        res = await send_aisensy_message(template_id, rec.phone, rec.parentName, base_source, template_params, media_dict)
        
        if res.get("success"):
            success_count += 1
            results.append({"phone": rec.phone, "status": "success", "messageId": res.get("messageId"), "id": rec.studentName})
        else:
            failed_count += 1
            results.append({"phone": rec.phone, "status": "failed", "error": res.get("error"), "id": rec.studentName})
            
        await asyncio.sleep(0.5)

    summary = { "jobId": job_id, "mode": "bulk", "total": len(payload.recipients), "success": success_count, "failed": failed_count, "skipped": skipped_count, "results": results }
    db = await connect_feeease()
    await update_usage_counter(db, payload.schoolId, success_count)
    if payload.webhookUrl:
        mongo_uri = school.get("deployment", {}).get("mongoDbUri", "")
        await deliver_webhook(payload.schoolId, str(payload.webhookUrl), job_id, summary, mongo_uri)


async def process_reminders_job(payload: ReminderRequest, school: dict, job_id: str):
    template_id = settings.AISENSY_TEMPLATES.get(f"reminder_{payload.language}", settings.AISENSY_TEMPLATES["reminder_english"])
    school_name = school.get("name", "Unknown School")
    base_source = payload.source or f"FeeEase - {school_name}"
    
    success_count = failed_count = skipped_count = 0
    results = []

    for rec in payload.recipients:
        if not rec.phone:
            skipped_count += 1
            results.append({"phone": "Unknown", "status": "skipped", "error": "No phone", "id": rec.studentName})
            continue

        template_params = [
            sanitize_param(rec.parentName),
            sanitize_param(school_name),
            sanitize_param(rec.studentName),
            sanitize_param(rec.dueAmount),
            sanitize_param(rec.month)
        ]

        res = await send_aisensy_message(template_id, rec.phone, rec.parentName, base_source, template_params)
        
        if res.get("success"):
            success_count += 1
            results.append({"phone": rec.phone, "status": "success", "messageId": res.get("messageId"), "id": rec.studentName})
        else:
            failed_count += 1
            results.append({"phone": rec.phone, "status": "failed", "error": res.get("error"), "id": rec.studentName})
            
        await asyncio.sleep(0.5)

    # Process Push Notifications (if any)
    if payload.pushTargets:
        push_data = {
            "title": "Fee Reminder",
            "body": f"Dear Parent, Fee for {school_name} is due. Please check details in the app.",
            "icon": "/logo.jpeg"
        }
        # Run push in background/non-blocking
        try:
            await broadcast_push_notifications(payload.pushTargets, push_data)

        except Exception as e:
            print(f"[Worker Error] Push broadcast failed: {e}")


    summary = { "jobId": job_id, "mode": "bulk", "total": len(payload.recipients), "success": success_count, "failed": failed_count, "skipped": skipped_count, "results": results }
    db = await connect_feeease()
    await update_usage_counter(db, payload.schoolId, success_count)
    if payload.webhookUrl:
        mongo_uri = school.get("deployment", {}).get("mongoDbUri", "")
        await deliver_webhook(payload.schoolId, str(payload.webhookUrl), job_id, summary, mongo_uri)


# -------------------------------------------------------------------------
# API Endpoints
# -------------------------------------------------------------------------

@router.post("/api/v1/whatsapp/broadcast/text")
async def broadcast_text(payload: NotificationRequest, background_tasks: BackgroundTasks):
    db = await connect_feeease()
    school, school_name = await validate_auth_limits(db, payload.schoolId, payload.licenseKey, len(payload.recipients))
    job_id = payload.jobId or str(uuid.uuid4())
    background_tasks.add_task(process_notification_job, payload, school, job_id, False)
    return {"success": True, "jobId": job_id, "status": "processing"}

@router.post("/api/v1/whatsapp/broadcast/image")
async def broadcast_image(payload: NotificationRequest, background_tasks: BackgroundTasks):
    if not payload.media:
        raise HTTPException(status_code=400, detail="Image broadcast requires media payload")
    db = await connect_feeease()
    school, school_name = await validate_auth_limits(db, payload.schoolId, payload.licenseKey, len(payload.recipients))
    job_id = payload.jobId or str(uuid.uuid4())
    background_tasks.add_task(process_notification_job, payload, school, job_id, True)
    return {"success": True, "jobId": job_id, "status": "processing"}

@router.post("/api/v1/whatsapp/reminders")
async def run_reminders(payload: ReminderRequest, background_tasks: BackgroundTasks):
    db = await connect_feeease()
    school, school_name = await validate_auth_limits(db, payload.schoolId, payload.licenseKey, len(payload.recipients))
    job_id = payload.jobId or str(uuid.uuid4())
    background_tasks.add_task(process_reminders_job, payload, school, job_id)
    return {"success": True, "jobId": job_id, "status": "processing"}

@router.post("/api/v1/whatsapp/receipt")
async def send_receipt(payload: ReceiptRequest):
    db = await connect_feeease()
    school, school_name = await validate_auth_limits(db, payload.schoolId, payload.licenseKey, 1)

    template_params = [
        sanitize_param(payload.parentName),
        sanitize_param(payload.studentName),
        sanitize_param(payload.amount),
        sanitize_param(payload.receiptNumber),
        sanitize_param(payload.month or ""),
        sanitize_param(school_name)
    ]
    media_dict = {"url": str(payload.media.url), "filename": payload.media.filename} if payload.media else None

    base_source = payload.source or f"FeeEase - {school_name}"
    res = await send_aisensy_message(settings.AISENSY_TEMPLATES["receipt"], payload.phone, payload.parentName, base_source, template_params, media_dict)

    if res.get("success"):
        await update_usage_counter(db, payload.schoolId, 1)
        return {"success": True, "messageId": res.get("messageId")}
    else:
        raise HTTPException(status_code=500, detail=res.get("error", "Unknown error"))


@router.post("/api/v1/whatsapp/otp")
async def send_otp(payload: OtpRequest):
    db = await connect_feeease()
    school, school_name = await validate_auth_limits(db, payload.schoolId, payload.licenseKey, 1)

    features = school.get("features", {})
    if not features.get("parentsLogin") and not features.get("teachersLogin"):
        raise HTTPException(status_code=403, detail="OTP Login is disabled for this school")

    template_params = [sanitize_param(payload.otp)]
    base_source = payload.source or f"FeeEase - {school_name}"

    button_params = {"text": sanitize_param(payload.otp)}
    buttons = [
        {
            "type": "button",
            "sub_type": "url",
            "index": 0,
            "parameters": [{"type": "text", "text": sanitize_param(payload.otp)}],
        }
    ]

    res = await send_aisensy_message(
        settings.AISENSY_TEMPLATES["otp"],
        payload.phone,
        payload.userName,
        base_source,
        template_params=template_params,
        button_params=button_params,
        buttons=buttons,
    )

    if res.get("success"):
        await update_usage_counter(db, payload.schoolId, 1)
        return {"success": True, "messageId": res.get("messageId")}
    else:
        raise HTTPException(status_code=500, detail=res.get("error", "Unknown error"))


@router.post("/api/v1/system/otp")
async def send_system_otp(
    payload: SystemOtpRequest, authorization: Optional[str] = Header(None)
):
    validate_webhook_secret(authorization)

    template_params = [sanitize_param(payload.otp)]
    base_source = payload.source or "FeeEase System"

    button_params = {"text": sanitize_param(payload.otp)}
    buttons = [
        {
            "type": "button",
            "sub_type": "url",
            "index": 0,
            "parameters": [{"type": "text", "text": sanitize_param(payload.otp)}],
        }
    ]

    res = await send_aisensy_message(
        settings.AISENSY_TEMPLATES["otp"],
        payload.phone,
        payload.userName,
        base_source,
        template_params=template_params,
        button_params=button_params,
        buttons=buttons,
    )

    if res.get("success"):
        return {"success": True, "messageId": res.get("messageId")}
    else:
        raise HTTPException(status_code=500, detail=res.get("error", "Unknown error"))

@router.post("/api/v1/app-notification")
async def send_app_push_notifications(payload: AppNotificationRequest, background_tasks: BackgroundTasks, x_license_key: str = Header(None)):
    if not x_license_key or x_license_key != payload.licenseKey:
        raise HTTPException(status_code=401, detail="Invalid license key")
    
    push_data = {
        "title": payload.title,
        "body": payload.body,
        "icon": payload.icon or "/logo.jpeg"
    }

    background_tasks.add_task(broadcast_push_notifications, payload.pushTargets, push_data)
    
    return {"success": True, "message": f"Push broadcast for {len(payload.pushTargets)} targets started."}

