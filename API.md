# FeeEase Worker - API Documentation

The `feeease-worker` is a Python/FastAPI microservice handling high-latency, bulk processing tasks for the FeeEase architecture (such as long-running push notifications to AiSensy endpoints) securely and asynchronously.

---

### Core Logic: Template Parameter Mapping

The worker automatically transforms incoming JSON payloads into the flat parameter arrays required by AiSensy. parameters are ordered to follow natural conversational flow.

#### 1. Universal Notification (Text/Image)
**Endpoint:** `POST /api/v1/whatsapp/broadcast/[text|image]`  
**Campaign Variable Count:** 5

| Input JSON Field | Worker sanitize Logic | AiSensy Placeholder | Description |
| :--- | :--- | :--- | :--- |
| `recipient.parentName` | Strips tabs/newlines | `{{1}}` | Dear [Parent Name] |
| `payload.notificationType` | Sanitized text | `{{2}}` | You've a new [Notification Type] |
| `payload.schoolName` | (System Auto-Injected) | `{{3}}` | from [School Name] |
| `recipient.studentName` | Strips tabs/newlines | `{{4}}` | regarding [Student Name] |
| `payload.mainMessage` | Strips formatted blocks | `{{5}}` | Message: [Main Message] |

**AiSensy Dashboard Template Design:**
> Dear {{1}},
> 
> You've a new {{2}} from {{3}} regarding {{4}}
> 
> Message: {{5}}
> 
> Reply "Stop" if you don't want to recive any future information from us.
> 
> _Thank You_

---

#### 2. Fee Due Reminders
**Endpoint:** `POST /api/v1/whatsapp/reminders`  
**Campaign Variable Count:** 5

| Input JSON Field | Worker sanitize Logic | AiSensy Placeholder | Description |
| :--- | :--- | :--- | :--- |
| `recipient.parentName` | Strips tabs/newlines | `{{1}}` | Dear [Parent Name] |
| `payload.schoolName` | (System Auto-Injected) | `{{2}}` | reminder from [School Name] |
| `recipient.studentName` | Strips tabs/newlines | `{{3}}` | for your ward [Student Name] |
| `recipient.dueAmount` | Currency sanitized | `{{4}}` | Total Due: [Amount] |
| `recipient.month` | Flat string block | `{{5}}` | Due Period: [Period] |

**AiSensy Dashboard Template Design:**
> Dear {{1}},
> 
> This is a friendly reminder from {{2}} about due fees for {{3}}
> Total Due: *{{4}}*
> Due Period: *{{5}}*
> 
> Reply *Stop* if you don't want to recieve any future updates.
> 
> _Thank You_

---

#### 3. Fee Receipt (Immediate)
**Endpoint:** `POST /api/v1/whatsapp/receipt`  
**Campaign Variable Count:** 6

| Input JSON Field | Worker sanitize Logic | AiSensy Placeholder | Example Output |
| :--- | :--- | :--- | :--- |
| `parentName` | Strips tabs/newlines | `{{1}}` | Jane Doe (Parent) |
| `studentName` | Strips tabs/newlines | `{{2}}` | John Doe (Student) |
| `amount` | Numeric string | `{{3}}` | 5000 (Amount) |
| `receiptNumber` | Flat string | `{{4}}` | 1025 (Receipt Number) |
| `month` | Flat string | `{{5}}` | January (Fee Period) |
| `schoolName` | (System Auto-Injected) | `{{6}}` | Modern Nursery (School) |

**AiSensy Dashboard Template Design:**
> Dear {{1}},
> 
> We have received fee payment for your ward {{2}} amounting to ₹{{3}}.
> Receipt Number: {{4}}
> Fee Period: {{5}}
> 
> Thank you for choosing {{6}}.

---

### Implementation Notes

1. **Wait times:** The worker enforces a 500ms sleep between individual messages in bulk mode to ensure stability and avoid AiSensy rate limits.
2. **Webhooks:** Once a job is finished, the worker hits the `webhookUrl` with a summary object.
3. **Authentication:** Every request must include a valid `schoolId` and `licenseKey`. The worker decrypts the school's private database URI to verify quotas before execution.
