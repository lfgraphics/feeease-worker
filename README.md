# FeeEase Worker (feeease-worker)

FeeEase Worker is a high-performance Python/FastAPI backend microservice tasked with executing heavy background calculations and batch processing outside of the core user interface thread.

As FeeEase (the admin panel) and its tenant projects (like `modern-nursery` and other modular schools) serve web interfaces in real time via Next.js and Vercel, serverless deployments naturally incur severe timeouts for long-running workflows (e.g. 10-second boundaries for Vercel Free / Pro tiers). 

**The FeeEase worker solves this by accepting "jobs" spanning multiple minutes to background process safely.**

## Primary Use Cases

1. **WhatsApp Broadcast Orchestration:** The core capability today. Next.js builds complex student rosters for notifications, reminders, or exam results and sends them via JSON lists to the worker. The worker chunks them, processes strict `AiSensy` structural validations, formats the templates correctly for variables, and delivers massive bulk webhook updates back to the front-end when completed, without Next.js Vercel functions silently dying mid-execution due to timeouts.

2. **Decoupled Business Logic:** Designed modularly so future features such as Biometric Integrations, C++ embedded software handlers, bulk Excel ingestion processing, or heavy database migrations can all securely attach to the architecture and be cleanly processed away from Next.js limitations.

## Core Features
*   **MongoDB Auto-resolving.** Decrypts individual school databases from the primary FeeEase tenant engine to act on individual databases.
*   **Usage Tracking.** Ensures the limits defined by `feeease` (License Key, Quotas) are respected.
*   **AiSensy Native Validation.** Sanitizes text and structural templates directly so they adhere strictly to string, tab, newline and sequential parameters defined by official WhatsApp marketing endpoints.
*   **Anti-Spam & Trust Measures.** Automatically injects verified school identity (from the licensed database) into sensitive communications like fee reminders and broadcast notifications to ensure recipients identify the source.

## Getting Started

1. Clone repo, setup `venv`.
2. Install pip modules `pip install -r requirements.txt`.
3. Provide `.env`. (See `.env.example`).
4. Run: `uvicorn app.main:app --host 0.0.0.0 --port 4000 --reload`
