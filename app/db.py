import os
import motor.motor_asyncio
from pymongo import MongoClient
import urllib.parse
from fastapi import Request

# Global connection to the central FeeEase DB
feeease_client: motor.motor_asyncio.AsyncIOMotorClient = None
feeease_db = None

async def connect_feeease():
    global feeease_client, feeease_db
    
    if feeease_client:
        return feeease_db

    uri = os.getenv("FEEEASE_MONGODB_URI", "")
    if not uri:
        raise ValueError("FEEEASE_MONGODB_URI is not set")

    feeease_client = motor.motor_asyncio.AsyncIOMotorClient(uri)
    
    # Extract DB name from URI or fallback to "test"
    parsed_uri = urllib.parse.urlparse(uri)
    db_name = parsed_uri.path[1:] if parsed_uri.path else "test"
    
    feeease_db = motor.motor_asyncio.AsyncIOMotorDatabase(feeease_client, db_name)
    return feeease_db

async def get_school_db(uri: str):
    """
    Creates an ephemeral connection to a specific school's DB.
    Does NOT cache it globally to prevent OOM errors over thousands of schools.
    """
    if not uri:
        raise ValueError("Missing mongoDbUri for school database")

    client = motor.motor_asyncio.AsyncIOMotorClient(uri, serverSelectionTimeoutMS=5000)
    
    parsed_uri = urllib.parse.urlparse(uri)
    db_name = parsed_uri.path[1:] if parsed_uri.path else "test"
    
    return motor.motor_asyncio.AsyncIOMotorDatabase(client, db_name), client
