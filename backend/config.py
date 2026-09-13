"""
Waste Segregation backend configuration.

All secrets/config should come from environment variables in production.
Sensible defaults are provided here so the prototype runs immediately.
"""
import os
from datetime import timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# --- Core config -----------------------------------------------------------
SECRET_KEY = os.environ.get("SECRET_KEY", "wastesegregation-dev-secret-change-me")
JWT_SECRET = os.environ.get("JWT_SECRET", "wastesegregation-jwt-dev-secret-change-me")
JWT_EXPIRY = timedelta(hours=int(os.environ.get("JWT_EXPIRY_HOURS", "12")))

DATABASE_PATH = os.environ.get(
    "DATABASE_PATH", os.path.join(BASE_DIR, "waste_segregation.db")
)

# Set to "1" to wipe and reseed the database on every startup (handy for demos).
RESEED_ON_START = os.environ.get("RESEED_ON_START", "0") == "1"

PORT = int(os.environ.get("PORT", "5000"))
HOST = os.environ.get("HOST", "0.0.0.0")
DEBUG = os.environ.get("FLASK_DEBUG", "1") == "1"

# --- Green Credit reward rules ---------------------------------------------
# Default credit awarded per rating. This is only the seed default -- the
# authoritative values live in the `credit_rules` table and can be changed
# at runtime by an admin via /api/admin/credit-rules, without touching code.
DEFAULT_CREDIT_RULES = {
    "GOOD": 10,
    "AVERAGE": 5,
    "POOR": 0,
}

RATINGS = ("GOOD", "AVERAGE", "POOR")
ROLES = ("HOUSEHOLD", "COLLECTOR", "ADMIN")
