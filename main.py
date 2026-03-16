import os
from dotenv import load_dotenv

# Load ENV before doing any deep application imports so module-level os.environ.get() picks it up
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import broadcast
from app.db import connect_feeease

load_dotenv()

app = FastAPI(
    title="FeeEase Background Worker",
    description="Handles async background jobs like WhatsApp broadcasting, PDF generation, & biometrics.",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    print("Connecting to central FeeEase MongoDB...")
    await connect_feeease()
    print("Worker is ready to accept jobs.")

@app.get("/")
async def root():
    return {"message": "FeeEase Background Worker is live 🚀", "service": "feeease-worker"}

@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "feeease-worker", "language": "python"}

# Include specific routers
app.include_router(broadcast.router)
