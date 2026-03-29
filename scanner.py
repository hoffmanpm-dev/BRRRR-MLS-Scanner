"""
BRRRR Scanner - Standalone scan engine.
Fetches from MLS Grid, filters, scores, and compares against history.
Can be used by both the Flask dashboard and the daily cron job.
"""

import re
import math
import urllib.parse
from datetime import datetime

import requests as http_requests

from config import *
from db import record_scan_results, log_scan


# ─── Filters ──────────────────────────────────────────────────────

LOT_KEYWORDS = [
    r"\bvacant\s+lot\b", r"\bvacant\s+land\b", r"\braw\s+land\b",
    r"\bbuildable\s+lot\b", r"\bland\s+only\b", r"\blot\s+for\s+sale\b",
    r"\bacreage\b", r"\bundeveloped\b", r"\bunimproved\b",
    r"\bno\s+structure\b", r"\btear\s*down\b", r"\bdemolish\b",
]

LAND_SUBTYPES = [
    "Unimproved Land", "Farm", "Ranch", "Vacant Land",
    "Agriculture", "Land", "Lots", "Acreage",
]


def is_valid_listing(l: dict) -> bool:
    """Return True if listing is a valid residential property (not a lot or junk)."""
    if not l.get("MlgCanView", True):
        return False
    price = l.get("ListPrice", 0)
    if not price or price < 15000:
        return False
    prop_type = (l.get("PropertyType") or "").strip()
    if prop_type in EXCLUDED_PROPERTY_TYPES:
        return False
    sub_type = (l.get("PropertySubType") or "").strip()
    if sub_type in LAND_SUBTYPES:
        return False
    sqft = l.get("LivingArea") or l.get("BuildingAreaTotal") or 0
    beds = l.get("BedroomsTotal") or 0
    if sqft == 0 and beds == 0:
        return False
    remarks = (l.get("PublicRemarks") or "").lower()
    for pattern in LOT_KEYWORDS:
        if re.search(pattern, remarks, re.IGNORECASE):
            return False
    return True


# ─── MLS Grid API ─────────────────────────────────────────────────

def fetch_listings() -> tuple:
    """
    Fetch listings from MLS Grid RESO Web API with pagination.
    Returns (list_of_raw_listings, list_of_errors).
    """
    status_filters = " or ".join(f"StandardStatus eq '{s}'" for s in LISTING_STATUSES)
    property_type_filters = " or ".join(f"PropertyType eq '{t}'" for t in PROPERTY_TYPES)

    odata_filter = (
        f"MlgCanView eq true"
        f" and ({status_filters})"
        f" and ({property_type_filters})"
    )

    headers = {
        "Authorization": f"Bearer {MLSGRID_TOKEN}",
        "Accept": "application/json",
    }

    url = f"{MLSGRID_API_BASE}/Property"
    params = {
        "$filter": odata_filter,
        "$top": 200,
        "$orderby": "ModificationTimestamp desc",
        "$expand": "Media",
    }

    all_results = []
    errors = []
    page = 0
    max_pages = 25

    while url and page < max_pages:
        try:
            if page == 0:
                resp = http_requests.get(url, headers=headers, params=params, timeout=60)
            else:
                resp = http_requests.get(url, headers=headers, timeout=60)

            print(f"  API response status: {resp.status_code}")
            if resp.status_code != 200:
                error_msg = f"MLS Grid returned HTTP {resp.status_code}: {resp.text[:500]}"
                print(f"[ERROR] {error_msg}")
                errors.append(error_msg)
                break

            data = resp.json()
        except http_requests.exceptions.ConnectionError as e:
            error_msg = f"Could not connect to MLS Grid API: {e}"
            print(f"[ERROR] {error_msg}")
            errors.append(error_msg)
            break
        except http_requests.exceptions.Timeout as e:
            error_msg = f"MLS Grid API timed out: {e}"
            print(f"[ERROR] {error_msg}")
            errors.append(error_msg)
            break
        except Exception as e:
            error_msg = f"Unexpected error: {type(e).__name__}: {e}"
            print(f"[ERROR] {error_msg}")
            errors.append(error_msg)
            break

        records = data.get("value", [])

        target_zips = set(TARGET_ZIP_CODES.keys())
        for r in records:
            zip_code = (r.get("PostalCode") or "")[:5]
            price = r.get("ListPrice") or 0
            if zip_code in target_zips and 15000 < price <= MAX_PURCHASE_PRICE:
                all_results.append(r)

        page += 1
        next_url = data.get("@odata.nextLink")
        print(f"  Page {page}: {len(records)} fetched, {len(all_results)} matched target zips so far")

        if not records or not next_url:
            break
        url = next_url

    if page >= max_pages:
        print(f"[WARN] Hit page limit ({max_pages}). Some listings may be missing.")

    return all_results, errors


# ─── BRRRR Scoring ────────────────────────────────────────────────

def score_property(l: dict) -> dict:
    """Score a single listing for BRRRR potential."""
    price = l.get("ListPrice", 0)
    zip_code = (l.get("PostalCode") or "")[:5]
    sqft = l.get("LivingArea") or l.get("BuildingAreaTotal") or 0
    ppsf = ARV_PPSF.get(zip_code, DEFAULT_ARV_PPSF)

    arv = sqft * ppsf if sqft > 0 else price / ARV_DISCOUNT_FACTOR
    rehab = price * DEFAULT_REHAB_PERCENT
    all_in = price + rehab
    max_offer_70 = arv * ARV_DISCOUNT_FACTOR
    meets_70 = all_in <= max_offer_70

    refi_loan = arv * REFI_LTV
    cash_left = max(0, all_in - refi_loan)
    equity_pct = (refi_loan / all_in * 100) if all_in > 0 else 0

    rent_mult = RENT_MULTIPLIERS.get(zip_code, DEFAULT_RENT_MULTIPLIER)
    monthly_rent = arv * rent_mult
    mr = REFI_INTEREST_RATE / 12
    n = REFI_TERM_YEARS * 12
    monthly_mortgage = refi_loan * (mr * (1 + mr)**n) / ((1 + mr)**n - 1) if refi_loan > 0 else 0

    annual_tax = l.get("TaxAnnualAmount") or 0
    monthly_tax = annual_tax / 12 if annual_tax > 0 else (arv * 0.015) / 12
    monthly_expenses = (
        monthly_mortgage + monthly_tax + MONTHLY_INSURANCE +
        monthly_rent * VACANCY_RATE + monthly_rent * MGMT_FEE_RATE +
        (arv * MONTHLY_MAINTENANCE_RATE) / 12
    )
    cashflow = monthly_rent - monthly_expenses
    annual_cf = cashflow * 12

    cap_rate = ((annual_cf + monthly_mortgage * 12) / arv * 100) if arv > 0 else 0
    coc = (annual_cf / cash_left * 100) if cash_left > 0 else 999

    score = 0
    if cashflow >= MIN_MONTHLY_CASHFLOW:
        score += min(25, 12 + (cashflow - MIN_MONTHLY_CASHFLOW) / 25)
    elif cashflow > 0:
        score += (cashflow / MIN_MONTHLY_CASHFLOW) * 12

    if equity_pct >= 100: score += 25
    elif equity_pct >= 90: score += 20
    elif equity_pct >= 80: score += 15
    elif equity_pct >= 70: score += 10

    if meets_70:
        score += 25
    else:
        gap = (all_in - max_offer_70) / max_offer_70 if max_offer_70 > 0 else 1
        score += max(0, 25 - gap * 100)

    if cap_rate >= 10: score += 25
    elif cap_rate >= 8: score += 20
    elif cap_rate >= 6: score += 12
    elif cap_rate >= 4: score += 6

    street = f"{l.get('StreetNumber', '')} {l.get('StreetName', '')} {l.get('StreetSuffix', '')}".strip()
    city = l.get("City", "")
    state = l.get("StateOrProvince", "")
    full_address = f"{street}, {city}, {state} {zip_code}"
    zillow_query = urllib.parse.quote(f"{street} {city} {state} {zip_code}")
    zillow_url = f"https://www.zillow.com/homes/{zillow_query}_rb/"

    photos = []
    media = l.get("Media") or l.get("media") or []
    if isinstance(media, list):
        for m in media:
            murl = m.get("MediaURL") or m.get("mediaURL") or m.get("Url") or m.get("url")
            if murl:
                photos.append(murl)
    photo_url = photos[0] if photos else None

    return {
        "id": l.get("ListingId", "N/A"),
        "key": l.get("ListingKey", ""),
        "address": street,
        "fullAddress": full_address,
        "city": city,
        "state": state,
        "zip": zip_code,
        "neighborhood": TARGET_ZIP_CODES.get(zip_code, ""),
        "lat": l.get("Latitude"),
        "lng": l.get("Longitude"),
        "price": round(price),
        "beds": l.get("BedroomsTotal") or 0,
        "baths": l.get("BathroomsTotalInteger") or 0,
        "sqft": sqft,
        "yearBuilt": l.get("YearBuilt") or 0,
        "dom": l.get("DaysOnMarket") or 0,
        "propertyType": l.get("PropertyType", ""),
        "status": l.get("StandardStatus", ""),
        "arv": round(arv),
        "rehab": round(rehab),
        "allIn": round(all_in),
        "refiLoan": round(refi_loan),
        "cashLeft": round(cash_left),
        "equityPct": round(equity_pct, 1),
        "monthlyRent": round(monthly_rent),
        "monthlyMortgage": round(monthly_mortgage),
        "monthlyExpenses": round(monthly_expenses),
        "cashflow": round(cashflow),
        "annualCashflow": round(annual_cf),
        "capRate": round(cap_rate, 2),
        "coc": round(coc, 2) if coc < 900 else 999,
        "meets70": meets_70,
        "score": round(score, 1),
        "zillowUrl": zillow_url,
        "photoUrl": photo_url,
        "photos": photos,
        "remarks": (l.get("PublicRemarks") or "")[:300],
    }


# ─── Full Scan Pipeline ──────────────────────────────────────────

def run_scan(track_changes=True) -> dict:
    """
    Run a complete scan: fetch -> filter -> score -> compare against history.

    Returns dict with:
        - properties: all viable scored properties
        - changes: dict with 'new', 'price_drops', 'price_increases', 'unchanged'
        - stats: summary counts
        - errors: any API errors
    """
    now = datetime.now()
    print(f"\n[{now.strftime('%H:%M:%S')}] Running BRRRR scan...")
    print(f"  Watching {len(TARGET_ZIP_CODES)} zip codes, max ${MAX_PURCHASE_PRICE:,}")

    raw, errors = fetch_listings()
    filtered = [l for l in raw if is_valid_listing(l)]
    scored = [score_property(l) for l in filtered]
    scored.sort(key=lambda x: x["score"], reverse=True)
    viable = [s for s in scored if s["cashflow"] > 0]

    changes = None
    if track_changes:
        changes = record_scan_results(viable)
        log_scan(
            total_raw=len(raw),
            total_filtered=len(filtered),
            total_viable=len(viable),
            new_count=len(changes["new"]),
            price_change_count=len(changes["price_drops"]) + len(changes["price_increases"]),
        )
        print(f"[SCAN] {len(changes['new'])} new, {len(changes['price_drops'])} price drops, "
              f"{len(changes['price_increases'])} price increases, {len(changes['unchanged'])} unchanged")

    print(f"[OK] {len(viable)} viable BRRRR deals found")

    return {
        "properties": viable,
        "changes": changes,
        "stats": {
            "totalRaw": len(raw),
            "totalFiltered": len(filtered),
            "totalViable": len(viable),
            "newListings": len(changes["new"]) if changes else 0,
            "priceDrops": len(changes["price_drops"]) if changes else 0,
            "priceIncreases": len(changes["price_increases"]) if changes else 0,
        },
        "errors": errors,
        "lastUpdated": now.isoformat(),
        "criteria": {
            "maxPrice": MAX_PURCHASE_PRICE,
            "minCashflow": MIN_MONTHLY_CASHFLOW,
            "refiRate": REFI_INTEREST_RATE * 100,
            "refiLtv": REFI_LTV * 100,
            "zips": list(TARGET_ZIP_CODES.keys()),
        },
    }
