import os

class Settings:
    # -------------------------------------------------------------------------
    # AiSensy Templates
    # -------------------------------------------------------------------------
    AISENSY_TEMPLATES = {
        "universal_text": os.getenv("AISENSY_TEMPLATE_UNIVERSAL_TEXT", "boradcast_text"),
        "universal_image": os.getenv("AISENSY_TEMPLATE_UNIVERSAL_IMAGE", "broadcast_image"),
        "receipt": os.getenv("AISENSY_TEMPLATE_RECEIPT", "fee_receipt_v1"),
        "otp": os.getenv("AISENSY_TEMPLATE_OTP", "login_otp"),
        "reminder_english": os.getenv("AISENSY_TEMPLATE_REMINDER_ENGLISH", "reminder_english"),
        "reminder_hindi": os.getenv("AISENSY_TEMPLATE_REMINDER_HINDI", "reminder_hindi"),
        "reminder_urdu": os.getenv("AISENSY_TEMPLATE_REMINDER_URDU", "reminder_urdu"),
    }

    # -------------------------------------------------------------------------
    # Picky Assist Templates
    # -------------------------------------------------------------------------
    PICKY_ASSIST_TEMPLATES = {
        "universal_text": os.getenv("PICKY_ASSIST_TEMPLATE_UNIVERSAL_TEXT", "boradcast_text"),
        "universal_image": os.getenv("PICKY_ASSIST_TEMPLATE_UNIVERSAL_IMAGE", "broadcast_image"),
        "receipt": os.getenv("PICKY_ASSIST_TEMPLATE_RECEIPT", "fee_receipt_v1"),
        "otp": os.getenv("PICKY_ASSIST_TEMPLATE_OTP", "login_otp"),
        "reminder_english": os.getenv("PICKY_ASSIST_TEMPLATE_REMINDER_ENGLISH", "reminder_english"),
        "reminder_hindi": os.getenv("PICKY_ASSIST_TEMPLATE_REMINDER_HINDI", "reminder_hindi"),
        "reminder_urdu": os.getenv("PICKY_ASSIST_TEMPLATE_REMINDER_URDU", "reminder_urdu"),
    }
    
    # -------------------------------------------------------------------------
    # Provider Settings
    # -------------------------------------------------------------------------
    PICKY_ASSIST_TOKEN = os.getenv("PICKY_ASSIST_TOKEN", "")
    PICKY_ASSIST_APPLICATION_ID = int(os.getenv("PICKY_ASSIST_APPLICATION_ID", "8"))
    
    AISENSY_API_KEY = os.getenv("AISENSY_API_KEY", "")
    AISENSY_BASE_URL = os.getenv("AISENSY_BASE_URL", "https://backend.aisensy.com/campaign/t1/api/v2")

settings = Settings()
