from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, HttpUrl
from typing import List, Optional, Dict, Any
from bson import ObjectId
from app.db import connect_feeease
from app.aisensy import send_aisensy_message
from app.webhook import deliver_webhook
import asyncio
import uuid
import re
from datetime import datetime
import os

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
    campaignName: str
    webhookUrl: HttpUrl
    jobId: Optional[str] = None
    source: Optional[str] = None
    notificationType: str
    mainMessage: str
    recipients: List[TextRecipientModel]
    media: Optional[MediaModel] = None

class ReminderRequest(BaseModel):
    schoolId: str
    licenseKey: str
    mode: str = "bulk"
    campaignName: str
    webhookUrl: HttpUrl
    jobId: Optional[str] = None
    source: Optional[str] = None
    recipients: List[ReminderRecipientModel]

class ReceiptRequest(BaseModel):
    schoolId: str
    licenseKey: str
    mode: str = "single"  # single
    campaignName: str
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
    campaignName: str
    phone: str
    userName: str
    otp: str
    validity: str = "5 minutes"
    source: Optional[str] = None


# -------------------------------------------------------------------------
# Utilities
# -------------------------------------------------------------------------
def sanitize_param(text: str) -> str:
    """Strictly strips newlines, tabs, and limits spaces to <4 for WhatsApp Guidelines."""
    if not text:
        return ""
    text = text.replace("\t", " ")
    text = re.sub(r'[\n\r]+', ' ', text)
    text = re.sub(r' {4,}', '   ', text)
    return text.strip()

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
        # 1. Try to increment if month matches
        res = await db.schools.update_one(
            {"_id": ObjectId(school_id), "whatsappUsage.monthYear": month_year},
            {"$inc": {"whatsappUsage.sentThisMonth": success_count}}
        )
        
        # 2. If no match, either it's a new month or missing usage object
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
async def process_notification_job(payload: NotificationRequest, school: dict, job_id: str):
    print(f"[Worker] Notification ({payload.campaignName}) for {payload.schoolId} ({len(payload.recipients)} recs)")
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
            sanitize_param(rec.parentName),   # {{1}} Dear [Parent]
            notif_type,                       # {{2}} a new [Notification Type]
            sanitize_param(school_name),      # {{3}} from [School Name]
            sanitize_param(rec.studentName),  # {{4}} regarding [Student]
            main_msg                          # {{5}} [Message]
        ]

        media_dict = {"url": str(payload.media.url), "filename": payload.media.filename} if payload.media else None

        res = await send_aisensy_message(payload.campaignName, rec.phone, rec.parentName, base_source, template_params, media_dict)
        
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
    print(f"[Worker] Reminders ({payload.campaignName}) for {payload.schoolId} ({len(payload.recipients)} recs)")
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
            sanitize_param(rec.parentName),    # {{1}} Dear [Parent]
            sanitize_param(school_name),       # {{2}} reminder from [School]
            sanitize_param(rec.studentName),   # {{3}} ward [Student]
            sanitize_param(rec.dueAmount),     # {{4}} Total due: [Amount]
            sanitize_param(rec.month)          # {{5}} Period: [Period]
        ]

        res = await send_aisensy_message(payload.campaignName, rec.phone, rec.parentName, base_source, template_params)
        
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


# -------------------------------------------------------------------------
# API Endpoints
# -------------------------------------------------------------------------

@router.post("/api/v1/whatsapp/broadcast/text")
async def broadcast_text(payload: NotificationRequest, background_tasks: BackgroundTasks):
    db = await connect_feeease()
    school, school_name = await validate_auth_limits(db, payload.schoolId, payload.licenseKey, len(payload.recipients))
    job_id = payload.jobId or str(uuid.uuid4())
    background_tasks.add_task(process_notification_job, payload, school, job_id)
    return {"success": True, "jobId": job_id, "status": "processing"}

@router.post("/api/v1/whatsapp/broadcast/image")
async def broadcast_image(payload: NotificationRequest, background_tasks: BackgroundTasks):
    if not payload.media:
        raise HTTPException(status_code=400, detail="Image broadcast requires media payload")
    db = await connect_feeease()
    school, school_name = await validate_auth_limits(db, payload.schoolId, payload.licenseKey, len(payload.recipients))
    job_id = payload.jobId or str(uuid.uuid4())
    background_tasks.add_task(process_notification_job, payload, school, job_id)
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
        sanitize_param(payload.parentName),   # {{1}}
        sanitize_param(payload.studentName),  # {{2}}
        sanitize_param(payload.amount),       # {{3}}
        sanitize_param(payload.receiptNumber),# {{4}}
        sanitize_param(payload.month or ""),  # {{5}}
        sanitize_param(school_name)            # {{6}}
    ]
    media_dict = {"url": str(payload.media.url), "filename": payload.media.filename} if payload.media else None

    base_source = payload.source or f"FeeEase - {school_name}"
    res = await send_aisensy_message(payload.campaignName, payload.phone, payload.parentName, base_source, template_params, media_dict)

    if res.get("success"):
        await update_usage_counter(db, payload.schoolId, 1)
        return {"success": True, "messageId": res.get("messageId")}
    else:
        raise HTTPException(status_code=500, detail=res.get("error", "Unknown error"))


@router.post("/api/v1/whatsapp/otp")
async def send_otp(payload: OtpRequest):
    db = await connect_feeease()
    school, school_name = await validate_auth_limits(
        db, payload.schoolId, payload.licenseKey, 1
    )

    # RBAC: Ensure parent or teacher login is enabled in centralized features
    features = school.get("features", {})
    if not features.get("parentsLogin") and not features.get("teachersLogin"):
        raise HTTPException(
            status_code=403, 
            detail="OTP Login is disabled for this school (Both Parents & Teachers portals are inactive)"
        )

    template_params = [
        sanitize_param(payload.otp),  # {{1}} OTP Code
    ]

    base_source = payload.source or f"FeeEase - {school_name}"

    # For Authentication templates, AiSensy Campaign API v2 can be tricky.
    # We send both the 'buttons' component list and the 'buttonParams' object to be safe.
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
        payload.campaignName,
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
