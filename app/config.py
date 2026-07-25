"""
All configuration in one place. Every value is read from environment
variables so nothing sensitive ever lives in code.
"""
import os
import json
from dotenv import load_dotenv

load_dotenv()  # This line actually reads the .env file into os.environ

# --- Twilio (WhatsApp) ---
TWILIO_ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN = os.environ["TWILIO_AUTH_TOKEN"]
# Twilio WhatsApp Sandbox number, format: "whatsapp:+14155238886"
TWILIO_WHATSAPP_FROM = os.environ["TWILIO_WHATSAPP_FROM"]
# Your personal WhatsApp number, format: "whatsapp:+91XXXXXXXXXX"
MY_WHATSAPP_NUMBER = os.environ["MY_WHATSAPP_NUMBER"]

# --- Google Sheets ---
GOOGLE_SERVICE_ACCOUNT_INFO = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
SHEET_ID = os.environ["SHEET_ID"]  # the Prep Tracker spreadsheet ID
SHEET_TAB_NAME = os.environ.get("SHEET_TAB_NAME", "Sheet1")

# --- Google Calendar ---
CALENDAR_ID = os.environ.get("CALENDAR_ID", "primary")

# --- Misc ---
TIMEZONE = "Asia/Kolkata"
# A shared secret so nobody but Twilio can hit your webhook and pretend to be you
WEBHOOK_SHARED_SECRET = os.environ.get("WEBHOOK_SHARED_SECRET", "")
