from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, HttpUrl
from typing import List, Optional, Dict, Any
from bson import ObjectId
from app.db import connect_feeease
from app.picky_assist import send_picky_assist_message
from app.webhook import deliver_webhook
from app.config import settings
import asyncio
import uuid
import re
from datetime import datetime
import os

router = APIRouter(prefix="/picky-assist/api/v1/whatsapp", tags=["Picky Assist WhatsApp"])

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

class ReminderRequest(BaseModel):
    schoolId: str
    licenseKey: str
    mode: str = "bulk"
    language: str = "english"
    webhookUrl: HttpUrl
    jobId: Optional[str] = None
    source: Optional[str] = None
    recipients: List[ReminderRecipientModel]

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
    validity: str = "5 minutes"
    source: Optional[str] = None


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
async def process_notification_job_picky(payload: NotificationRequest, school: dict, job_id: str, is_image: bool = False):
    template_id = settings.PICKY_ASSIST_TEMPLATES["universal_image"] if is_image else settings.PICKY_ASSIST_TEMPLATES["universal_text"]
    school_name = school.get("name", "Unknown School")
    print(f"[Worker/Picky] Notification ({template_id}) for {payload.schoolId} ({len(payload.recipients)} recs)")
    
    picky_recipients = []
    notif_type = sanitize_param(payload.notificationType)
    main_msg = sanitize_param(payload.mainMessage)

    for rec in payload.recipients:
        template_vars = [
            sanitize_param(rec.parentName),
            notif_type,
            sanitize_param(school_name),
            sanitize_param(rec.studentName),
            main_msg
        ]
        entry = {
            "number": rec.phone,
            "template_message": template_vars,
            "language": "en"
        }
        if payload.media:
            entry["media"] = str(payload.media.url)
        picky_recipients.append(entry)

    res = await send_picky_assist_message(
        template_id=template_id,
        recipients=picky_recipients
    )

    success_count = 0
    failed_count = 0
    results = []

    if res.get("success"):
        success_count = len(picky_recipients)
        for rec in payload.recipients:
            results.append({"phone": rec.phone, "status": "success", "id": rec.studentName})
    else:
        failed_count = len(picky_recipients)
        err = res.get("error", "Picky Assist Batch Failure")
        for rec in payload.recipients:
            results.append({"phone": rec.phone, "status": "failed", "error": err, "id": rec.studentName})

    summary = { "jobId": job_id, "mode": "bulk", "total": len(payload.recipients), "success": success_count, "failed": failed_count, "results": results }
    db = await connect_feeease()
    await update_usage_counter(db, payload.schoolId, success_count)
    if payload.webhookUrl:
        mongo_uri = school.get("deployment", {}).get("mongoDbUri", "")
        await deliver_webhook(payload.schoolId, str(payload.webhookUrl), job_id, summary, mongo_uri)

async def process_reminders_job_picky(payload: ReminderRequest, school: dict, job_id: str):
    school_name = school.get("name", "Unknown School")
    template_id = settings.PICKY_ASSIST_TEMPLATES.get(f"reminder_{payload.language}", settings.PICKY_ASSIST_TEMPLATES["reminder_english"])
    print(f"[Worker/Picky] Reminders ({template_id}) for {payload.schoolId} ({len(payload.recipients)} recs)")
    
    picky_recipients = []
    for rec in payload.recipients:
        template_vars = [
            sanitize_param(rec.parentName),
            sanitize_param(school_name),
            sanitize_param(rec.studentName),
            sanitize_param(rec.dueAmount),
            sanitize_param(rec.month)
        ]
        picky_recipients.append({
            "number": rec.phone,
            "template_message": template_vars,
            "language": "en"
        })

    res = await send_picky_assist_message(
        template_id=template_id,
        recipients=picky_recipients
    )

    success_count = 0
    failed_count = 0
    results = []

    if res.get("success"):
        success_count = len(picky_recipients)
        for rec in payload.recipients:
            results.append({"phone": rec.phone, "status": "success", "id": rec.studentName})
    else:
        failed_count = len(picky_recipients)
        err = res.get("error", "Picky Assist Batch Failure")
        for rec in payload.recipients:
            results.append({"phone": rec.phone, "status": "failed", "error": err, "id": rec.studentName})

    summary = { "jobId": job_id, "mode": "bulk", "total": len(payload.recipients), "success": success_count, "failed": failed_count, "results": results }
    db = await connect_feeease()
    await update_usage_counter(db, payload.schoolId, success_count)
    if payload.webhookUrl:
        mongo_uri = school.get("deployment", {}).get("mongoDbUri", "")
        await deliver_webhook(payload.schoolId, str(payload.webhookUrl), job_id, summary, mongo_uri)

# -------------------------------------------------------------------------
# API Endpoints
# -------------------------------------------------------------------------

@router.post("/broadcast/text")
async def broadcast_text_picky(payload: NotificationRequest, background_tasks: BackgroundTasks):
    db = await connect_feeease()
    school, school_name = await validate_auth_limits(db, payload.schoolId, payload.licenseKey, len(payload.recipients))
    job_id = payload.jobId or str(uuid.uuid4())
    background_tasks.add_task(process_notification_job_picky, payload, school, job_id, False)
    return {"success": True, "jobId": job_id, "status": "processing"}

@router.post("/broadcast/image")
async def broadcast_image_picky(payload: NotificationRequest, background_tasks: BackgroundTasks):
    if not payload.media:
        raise HTTPException(status_code=400, detail="Image broadcast requires media payload")
    db = await connect_feeease()
    school, school_name = await validate_auth_limits(db, payload.schoolId, payload.licenseKey, len(payload.recipients))
    job_id = payload.jobId or str(uuid.uuid4())
    background_tasks.add_task(process_notification_job_picky, payload, school, job_id, True)
    return {"success": True, "jobId": job_id, "status": "processing"}

@router.post("/reminders")
async def run_reminders_picky(payload: ReminderRequest, background_tasks: BackgroundTasks):
    db = await connect_feeease()
    school, school_name = await validate_auth_limits(db, payload.schoolId, payload.licenseKey, len(payload.recipients))
    job_id = payload.jobId or str(uuid.uuid4())
    background_tasks.add_task(process_reminders_job_picky, payload, school, job_id)
    return {"success": True, "jobId": job_id, "status": "processing"}

@router.post("/receipt")
async def send_receipt_picky(payload: ReceiptRequest):
    db = await connect_feeease()
    school, school_name = await validate_auth_limits(db, payload.schoolId, payload.licenseKey, 1)

    template_vars = [
        sanitize_param(payload.parentName),
        sanitize_param(payload.studentName),
        sanitize_param(payload.amount),
        sanitize_param(payload.receiptNumber),
        sanitize_param(payload.month or ""),
        sanitize_param(school_name)
    ]
    
    res = await send_picky_assist_message(
        template_id=settings.PICKY_ASSIST_TEMPLATES["receipt"],
        recipients=[{
            "number": payload.phone,
            "template_message": template_vars,
            "media": str(payload.media.url) if payload.media else None
        }]
    )

    if res.get("success"):
        await update_usage_counter(db, payload.schoolId, 1)
        return {"success": True, "messageId": "sent"}
    else:
        raise HTTPException(status_code=500, detail=res.get("error", "Unknown error"))

@router.post("/otp")
async def send_otp_picky(payload: OtpRequest):
    db = await connect_feeease()
    school, school_name = await validate_auth_limits(db, payload.schoolId, payload.licenseKey, 1)

    template_vars = [sanitize_param(payload.otp)]
    
    res = await send_picky_assist_message(
        template_id=settings.PICKY_ASSIST_TEMPLATES["otp"],
        recipients=[{"number": payload.phone, "template_message": template_vars}]
    )

    if res.get("success"):
        await update_usage_counter(db, payload.schoolId, 1)
        return {"success": True, "messageId": "sent"}
    else:
        raise HTTPException(status_code=500, detail=res.get("error", "Unknown error"))
