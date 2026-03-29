"""
BRRRR Dashboard - Configuration
"""

import os

# ─── MLS Grid API ────────────────────────────────────────────────
MLSGRID_API_BASE = "https://api.mlsgrid.com/v2"
MLSGRID_TOKEN = os.environ.get("MLSGRID_TOKEN", "79c5d28fe418d7bb2fdcbd4f292514e309ea80cd")

# ─── Target Markets ──────────────────────────────────────────────
TARGET_ZIP_CODES = {
    "63130": "University City, MO",
    "63143": "Maplewood, MO",
    "63139": "Lindenwood Park, MO",
    "63104": "Soulard / Benton Park, MO",
    "63110": "Tower Grove, MO",
    "63116": "Dutchtown / Gravois Park, MO",
    "93117": "Goleta / Santa Barbara, CA",
}

# ─── BRRRR Criteria ──────────────────────────────────────────────
MAX_PURCHASE_PRICE = 500_000
ARV_DISCOUNT_FACTOR = 0.70
MIN_MONTHLY_CASHFLOW = 300
DEFAULT_REHAB_PERCENT = 0.15
REFI_LTV = 0.75
REFI_INTEREST_RATE = 0.07
REFI_TERM_YEARS = 30
VACANCY_RATE = 0.08
MGMT_FEE_RATE = 0.10
MONTHLY_INSURANCE = 150
MONTHLY_MAINTENANCE_RATE = 0.01

# ─── Rent & ARV Estimates Per Zip ────────────────────────────────
RENT_MULTIPLIERS = {
    "63130": 0.0075, "63143": 0.0080, "63139": 0.0085,
    "63104": 0.0090, "63110": 0.0085, "63116": 0.0090,
    "93117": 0.0050,
}
DEFAULT_RENT_MULTIPLIER = 0.0075

ARV_PPSF = {
    "63130": 160, "63143": 170, "63139": 145,
    "63104": 175, "63110": 165, "63116": 130,
    "93117": 650,
}
DEFAULT_ARV_PPSF = 160

# ─── Filters ─────────────────────────────────────────────────────
PROPERTY_TYPES = ["Residential", "ResidentialIncome"]
LISTING_STATUSES = ["Active", "Coming Soon"]
EXCLUDED_PROPERTY_TYPES = ["Land", "Farm", "Commercial Sale", "Business Opportunity"]

# ─── Gemini AI Analysis ─────────────────────────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "AIzaSyDPzqjRNrv2vD170vRe-9KF9j6V6QHzHY0")
GEMINI_MODEL = "gemini-2.0-flash"
