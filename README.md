# FeeEase WhatsApp Worker

Centralized background worker for handling WhatsApp notifications via AiSensy and Picky Assist.

## Environment Variables

Configure these variables in your worker's `.env` file or environment settings.

### Provider Credentials
| Variable | Description |
| :--- | :--- |
| `PICKY_ASSIST_TOKEN` | API Token from Picky Assist Push API (V2). |
| `PICKY_ASSIST_APPLICATION_ID` | Application ID from Picky Assist (typically 8). Default is 8. |
| `AISENSY_API_KEY` | API Key from AiSensy Campaign API. |
| `AISENSY_BASE_URL` | AiSensy API Endpoint. Default is `https://backend.aisensy.com/campaign/t1/api/v2`. |

### Template Mapping (AiSensy)
| Variable | Default Value |
| :--- | :--- |
| `AISENSY_TEMPLATE_UNIVERSAL_TEXT` | `boradcast_text` |
| `AISENSY_TEMPLATE_UNIVERSAL_IMAGE` | `broadcast_image` |
| `AISENSY_TEMPLATE_RECEIPT` | `fee_receipt_v1` |
| `AISENSY_TEMPLATE_OTP` | `login_otp` |
| `AISENSY_TEMPLATE_REMINDER_ENGLISH` | `reminder_english` |
| `AISENSY_TEMPLATE_REMINDER_HINDI` | `reminder_hindi` |
| `AISENSY_TEMPLATE_REMINDER_URDU` | `reminder_urdu` |

### Template Mapping (Picky Assist)
| Variable | Default Value |
| :--- | :--- |
| `PICKY_ASSIST_TEMPLATE_UNIVERSAL_TEXT` | `boradcast_text` |
| `PICKY_ASSIST_TEMPLATE_UNIVERSAL_IMAGE` | `broadcast_image` |
| `PICKY_ASSIST_TEMPLATE_RECEIPT` | `fee_receipt_v1` |
| `PICKY_ASSIST_TEMPLATE_OTP` | `login_otp` |
| `PICKY_ASSIST_TEMPLATE_REMINDER_ENGLISH` | `reminder_english` |
| `PICKY_ASSIST_TEMPLATE_REMINDER_HINDI` | `reminder_hindi` |
| `PICKY_ASSIST_TEMPLATE_REMINDER_URDU` | `reminder_urdu` |

---

## Recommended Template Body Structures

When creating templates in AiSensy or Picky Assist, use the following structures for the variables to match the worker's payloads.

### 1. Fee Receipt (`receipt`)
**Context**: Sent after a successful fee payment. Includes a media attachment (the receipt image).
**Body**:
> Dear **{{1}}**, Fee payment for student **{{2}}** of amount **{{3}}** is successful with receipt no **{{4}}** for the month **{{5}}**.
*   `{{1}}`: Parent Name
*   `{{2}}`: Student Name
*   `{{3}}`: Amount
*   `{{4}}`: Receipt Number
*   `{{5}}`: Month/Session

### 2. Fee Reminders (`reminder_...`)
**Context**: Bulk reminders sent to parents for unpaid fees.
**Body**:
> Dear **{{1}}**, This is a reminder from **{{2}}** for student **{{3}}**. An amount of **{{4}}** is due for **{{5}}**. Please pay soon.
*   `{{1}}`: Parent Name
*   `{{2}}`: School Name
*   `{{3}}`: Student Name
*   `{{4}}`: Due Amount
*   `{{5}}`: Month/Session

### 3. Login OTP (`otp`)
**Context**: Authentication codes for parents or teachers.
**Body**:
> Your login OTP for FeeEase is **{{1}}**. Please do not share this code with anyone.
*   `{{1}}`: OTP Code

### 4. Universal Broadcasts (`universal_text` / `universal_image`)
**Context**: General announcements from the school.
**Body**:
> Dear **{{1}}**, This is an update from **{{2}}**:
> 
> **{{3}}**
*   `{{1}}`: Recipient Name
*   `{{2}}`: School Name
*   `{{3}}`: Message Body

---

## Technical Architecture

The worker implements a **Split-Provider Proxy Architecture**:
1.  **Platform Neutral**: The central platform (`feeease`) and school applications (`modern-nursery`) do not store template IDs.
2.  **Endpoint Routing**: Provider selection is handled by the URL path:
    *   AiSensy: `POST /api/v1/whatsapp/[action]`
    *   Picky Assist: `POST /picky-assist/api/v1/whatsapp/[action]`
3.  **Variable Masking**: The worker handles the transformation between AiSensy's `template { title, params }` format and Picky Assist's `recipients [{ number, template_message }]` format automatically.
