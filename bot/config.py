"""
bot/config.py — Gmail credentials only.

Strategy parameters have moved to config/strategy.yaml.
Load them anywhere via:  from core.config import load_config
"""

import os
from dotenv import load_dotenv

load_dotenv()

GMAIL_SENDER   = os.getenv("GMAIL_SENDER")
GMAIL_APP_PASS = os.getenv("GMAIL_APP_PASS")

_raw = os.getenv("ALERT_RECIPIENTS", os.getenv("ALERT_RECIPIENT", ""))
ALERT_RECIPIENTS: list[str] = [r.strip() for r in _raw.split(",") if r.strip()]
