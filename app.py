#!/usr/bin/env python3
"""
BRRRR Dashboard - Flask Web Application
Connects to MLS Grid RESO Web API, scores properties for BRRRR potential,
and serves a clean dashboard with Zillow links.
"""

import base64
import json
import hashlib
import math
import re
import os
import time
import threading
import urllib.parse
from datetime import datetime, timedelta
from flask import Flask, render_template, jsonify, request, Response, send_file

import requests as http_requests
from google import genai
from google.genai import types

from config import *
from scanner import run_scan, fetch_listings, is_valid_listing, score_property

# ─── Gemini Client ───────────────────────────────────────────────
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
_ai_cache = {}  # listingId -> analysis result

app = Flask(__name__)

# ─── Cache ────────────────────────────────────────────────────────
_cache = {"data": None, "timestamp": None}
CACHE_TTL_MINUTES = 60  # re-fetch from MLS Grid every 60 minutes

# ─── Photo Cache ──────────────────────────────────────────────────
PHOTO_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "photo_cache")
os.makedirs(PHOTO_CACHE_DIR, exist_ok=True)
_photo_fetch_lock = threading.Lock()


def _url_to_cache_path(url):
    """Convert a URL to a local cache file path."""
    url_hash = hashlib.md5(url.encode()).hexdigest()
    # Try to get extension from URL
    ext = ".jpeg"
    if ".png" in url.lower():
        ext = ".png"
    return os.path.join(PHOTO_CACHE_DIR, f"{url_hash}{ext}")


def _fetch_and_cache_photo(url, cache_path, max_retries=3):
    """Fetch a photo from MLS Grid with retry on 429, save to cache."""
    headers = {
        "Authorization": f"Bearer {MLSGRID_TOKEN}",
        "Accept": "image/jpeg,image/png,image/*,*/*",
    }
    for attempt in range(max_retries):
        try:
            resp = http_requests.get(url, timeout=15, headers=headers)
            if resp.status_code == 200:
                content_type = resp.headers.get("Content-Type", "")
                if "image" in content_type and len(resp.content) > 100:
                    with open(cache_path, "wb") as f:
                        f.write(resp.content)
                    return True
                else:
                    print(f"[PHOTO] Non-image response: {content_type}, {len(resp.content)} bytes")
                    return False
            elif resp.status_code == 429:
                wait = (attempt + 1) * 2  # 2s, 4s, 6s
                print(f"[PHOTO] Rate limited (429), waiting {wait}s... (attempt {attempt+1}/{max_retries})")
                time.sleep(wait)
            else:
                print(f"[PHOTO] HTTP {resp.status_code} for {url[:80]}...")
                return False
        except Exception as e:
            print(f"[PHOTO] Error: {e}")
            return False
    return False


def prefetch_photos(properties):
    """Background: download only COVER photos with rate limiting. Gallery photos load on-demand."""
    urls = []
    for p in properties:
        if p.get("photoUrl"):
            urls.append(p["photoUrl"])

    uncached = [(u, _url_to_cache_path(u)) for u in urls if not os.path.exists(_url_to_cache_path(u))]
    if not uncached:
        print(f"[PHOTO] All {len(urls)} cover photos already cached")
        return

    print(f"[PHOTO] Pre-fetching {len(uncached)} cover photos (of {len(urls)} total)...")
    success = 0
    for i, (url, path) in enumerate(uncached):
        if _fetch_and_cache_photo(url, path):
            success += 1
        # Rate limit: ~1 request per 0.5 seconds to avoid 429
        if i < len(uncached) - 1:
            time.sleep(0.5)
        if (i + 1) % 20 == 0:
            print(f"[PHOTO]   ...{i+1}/{len(uncached)} fetched ({success} ok)")

    print(f"[PHOTO] Pre-fetch done: {success}/{len(uncached)} cover photos cached")


# ─── Data Pipeline ────────────────────────────────────────────────

def get_scored_properties(force_refresh=False) -> dict:
    """Fetch, filter, score, and cache properties. Uses the scanner module."""
    now = datetime.now()

    if (not force_refresh and _cache["data"] and _cache["timestamp"]
            and (now - _cache["timestamp"]).total_seconds() < CACHE_TTL_MINUTES * 60):
        return _cache["data"]

    # Use the shared scanner module
    scan = run_scan(track_changes=True)

    viable = scan["properties"]
    result = {
        "properties": viable,
        "totalRaw": scan["stats"]["totalRaw"],
        "totalFiltered": scan["stats"]["totalFiltered"],
        "totalViable": scan["stats"]["totalViable"],
        "lastUpdated": scan["lastUpdated"],
        "errors": scan["errors"],
        "changes": scan["changes"],
        "criteria": scan["criteria"],
    }

    _cache["data"] = result
    _cache["timestamp"] = now
    print(f"[OK] {len(viable)} viable BRRRR deals cached")

    # Kick off background photo download
    thread = threading.Thread(target=prefetch_photos, args=(viable,), daemon=True)
    thread.start()

    return result


# ─── Routes ───────────────────────────────────────────────────────

@app.route("/")
def dashboard():
    return render_template("dashboard.html")


@app.route("/api/prefetch-gallery", methods=["POST"])
def prefetch_gallery():
    """Pre-cache all gallery photos for a specific property (called when user clicks into a listing)."""
    data = request.get_json() or {}
    urls = data.get("urls", [])
    if not urls:
        return jsonify({"cached": 0}), 200

    def _bg_fetch(photo_urls):
        cached = 0
        for url in photo_urls:
            path = _url_to_cache_path(url)
            if os.path.exists(path) and os.path.getsize(path) > 100:
                cached += 1
                continue
            if _fetch_and_cache_photo(url, path):
                cached += 1
            time.sleep(0.3)  # rate limit
        print(f"[PHOTO] Gallery pre-fetch: {cached}/{len(photo_urls)} cached")

    thread = threading.Thread(target=_bg_fetch, args=(urls,), daemon=True)
    thread.start()
    return jsonify({"queued": len(urls)}), 200


@app.route("/api/properties")
def api_properties():
    force = request.args.get("refresh", "").lower() == "true"
    data = get_scored_properties(force_refresh=force)
    return jsonify(data)


@app.route("/api/ai-analysis", methods=["POST"])
def ai_analysis():
    """Use Gemini to analyze a property's photos and data for BRRRR investment potential."""
    if not gemini_client:
        return jsonify({"error": "Gemini API key not configured"}), 500

    req_data = request.get_json() or {}
    listing_id = req_data.get("listingId")
    if not listing_id:
        return jsonify({"error": "Missing listingId"}), 400

    # Check AI cache first
    if listing_id in _ai_cache:
        print(f"[AI] Serving cached analysis for {listing_id}")
        return jsonify(_ai_cache[listing_id])

    # Find the property in cached data
    data = get_scored_properties()
    props = data.get("properties", [])
    prop = next((p for p in props if p.get("id") == listing_id), None)
    if not prop:
        return jsonify({"error": f"Property {listing_id} not found"}), 404

    # Gather up to 5 photos as base64 for Gemini vision
    photo_parts = []
    photo_urls = (prop.get("photos") or [])[:5]
    for url in photo_urls:
        cache_path = _url_to_cache_path(url)
        if os.path.exists(cache_path) and os.path.getsize(cache_path) > 100:
            with open(cache_path, "rb") as f:
                img_bytes = f.read()
            mime = "image/png" if cache_path.endswith(".png") else "image/jpeg"
            photo_parts.append(types.Part.from_bytes(data=img_bytes, mime_type=mime))

    # Build the analysis prompt
    prompt = f"""You are an expert real estate investment analyst specializing in the BRRRR strategy (Buy, Rehab, Rent, Refinance, Repeat).

Analyze this property based on the photos and listing data provided.

## Property Details
- **Address:** {prop.get('fullAddress', 'N/A')}
- **List Price:** ${prop.get('price', 0):,}
- **Beds/Baths:** {prop.get('beds', 0)} bd / {prop.get('baths', 0)} ba
- **Sq Ft:** {prop.get('sqft', 0):,}
- **Year Built:** {prop.get('yearBuilt', 'Unknown')}
- **Days on Market:** {prop.get('dom', 0)}
- **Property Type:** {prop.get('propertyType', 'N/A')}
- **Status:** {prop.get('status', 'N/A')}
- **Neighborhood:** {prop.get('neighborhood', 'N/A')}

## BRRRR Metrics (Calculated)
- **BRRRR Score:** {prop.get('score', 0)}/100
- **Estimated ARV:** ${prop.get('arv', 0):,}
- **Estimated Rehab (15% of price):** ${prop.get('rehab', 0):,}
- **All-In Cost:** ${prop.get('allIn', 0):,}
- **Refi Loan (75% LTV):** ${prop.get('refiLoan', 0):,}
- **Cash Left in Deal:** ${prop.get('cashLeft', 0):,}
- **Equity Out:** {prop.get('equityPct', 0)}%
- **Monthly Rent Estimate:** ${prop.get('monthlyRent', 0):,}
- **Monthly Cashflow:** ${prop.get('cashflow', 0):,}
- **Cap Rate:** {prop.get('capRate', 0)}%
- **Meets 70% Rule:** {'Yes' if prop.get('meets70') else 'No'}

## Listing Remarks
{prop.get('remarks', 'No remarks available.')}

## Your Analysis

Please provide a structured assessment with these sections:

### PROPERTY CONDITION
Based on the photos, assess the exterior and interior condition. Comment on curb appeal, visible damage, deferred maintenance, and overall state.

### REHAB ASSESSMENT
Based on what you see in the photos and the property details, does the estimated rehab cost of ${prop.get('rehab', 0):,} (15% of list price) seem reasonable? What major rehab items do you see? Provide a rough rehab cost range if the 15% estimate seems off.

### RED FLAGS
Identify any concerning issues visible in the photos or listing data — structural problems, water damage, foundation issues, roof condition, outdated systems, environmental risks, or anything that warrants further investigation.

### INVESTMENT VERDICT
Rate this as a BRRRR investment: **STRONG BUY**, **BUY**, **HOLD**, or **PASS**.
Explain your reasoning based on the numbers AND what you see in the photos.

### KEY RECOMMENDATIONS
List 3-5 specific action items for the investor — what to inspect, negotiate on, or be cautious about.

Be direct and practical. This is for an experienced investor who wants actionable insights, not generic advice."""

    # Build Gemini request with photos + prompt
    contents = []
    if photo_parts:
        contents.extend(photo_parts)
    contents.append(prompt)

    try:
        print(f"[AI] Analyzing {listing_id} ({prop.get('address')}) with {len(photo_parts)} photos...")
        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=contents,
        )
        analysis_text = response.text
        print(f"[AI] Analysis complete for {listing_id} ({len(analysis_text)} chars)")

        result = {
            "listingId": listing_id,
            "address": prop.get("address", ""),
            "analysis": analysis_text,
            "photosAnalyzed": len(photo_parts),
            "timestamp": datetime.now().isoformat(),
        }

        # Cache it
        _ai_cache[listing_id] = result
        return jsonify(result)

    except Exception as e:
        print(f"[AI] Error analyzing {listing_id}: {e}")
        return jsonify({"error": f"Gemini API error: {str(e)}"}), 500


@app.route("/api/photo")
def photo_proxy():
    """Serve MLS Grid photos from local cache. Fetch if not cached yet."""
    url = request.args.get("url", "")
    if not url:
        return "Missing url parameter", 400

    cache_path = _url_to_cache_path(url)

    # Serve from cache if available
    if os.path.exists(cache_path) and os.path.getsize(cache_path) > 100:
        content_type = "image/png" if cache_path.endswith(".png") else "image/jpeg"
        return send_file(cache_path, mimetype=content_type, max_age=3600)

    # Not cached — fetch with rate limiting (blocking, single-threaded per request)
    with _photo_fetch_lock:
        # Double-check after acquiring lock
        if os.path.exists(cache_path) and os.path.getsize(cache_path) > 100:
            content_type = "image/png" if cache_path.endswith(".png") else "image/jpeg"
            return send_file(cache_path, mimetype=content_type, max_age=3600)

        if _fetch_and_cache_photo(url, cache_path):
            content_type = "image/png" if cache_path.endswith(".png") else "image/jpeg"
            return send_file(cache_path, mimetype=content_type, max_age=3600)

    # All retries failed
    return "Photo unavailable (rate limited by MLS Grid, try refreshing in a minute)", 503


@app.route("/api/test-photo")
def test_photo():
    """Diagnostic page: tests photo caching and loading."""
    data = get_scored_properties()
    props = data.get("properties", [])
    if not props or not props[0].get("photoUrl"):
        return "<h1>No properties with photos found</h1>", 200

    first_url = props[0]["photoUrl"]
    proxy_url = f"/api/photo?url={urllib.parse.quote(first_url, safe='')}"
    address = props[0].get("address", "Unknown")
    cache_path = _url_to_cache_path(first_url)
    is_cached = os.path.exists(cache_path)
    cache_size = os.path.getsize(cache_path) if is_cached else 0

    # Count total cached photos
    total_cached = len([f for f in os.listdir(PHOTO_CACHE_DIR) if os.path.getsize(os.path.join(PHOTO_CACHE_DIR, f)) > 100])
    total_props_with_photos = sum(1 for p in props if p.get("photoUrl"))

    return f"""<!DOCTYPE html>
<html><head><title>Photo Test</title></head>
<body style="background:#111;color:#eee;font-family:sans-serif;padding:20px;">
<h1>Photo Loading Test v3 — Cache Mode</h1>
<h2>Property: {address}</h2>

<h3>Cache Status:</h3>
<p style="color:{'#0f0' if is_cached else '#f66'};font-family:monospace;">
    This photo cached: {'YES' if is_cached else 'NO'} ({cache_size} bytes)<br>
    Total photos cached: {total_cached} / {total_props_with_photos}<br>
    Cache dir: {PHOTO_CACHE_DIR}
</p>
<p style="color:#888;">Photos are downloaded in the background after listings load. Wait ~2 minutes for all photos to cache, then refresh this page.</p>

<hr>

<h3>Photo via proxy (from cache):</h3>
<img src="{proxy_url}" style="max-width:500px;border:2px solid green;" onerror="this.alt='NOT CACHED YET — wait for background download to finish, then refresh'">

<hr>
<p style="color:#888;">If the photo doesn't appear, check the terminal for [PHOTO] log messages showing download progress. Once cached, photos load instantly.</p>
</body></html>"""


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "time": datetime.now().isoformat()})


@app.route("/api/debug-photos")
def debug_photos():
    """Debug: show photo URLs for the first 3 properties."""
    data = get_scored_properties()
    props = data.get("properties", [])[:3]
    debug = []
    for p in props:
        debug.append({
            "address": p.get("address"),
            "photoUrl": p.get("photoUrl"),
            "photoCount": len(p.get("photos", [])),
            "first3Photos": p.get("photos", [])[:3],
        })
    return jsonify(debug)


# ─── Main ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    host = os.environ.get("HOST", "127.0.0.1")  # use 127.0.0.1 locally to avoid macOS firewall
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    print(f"\n  BRRRR Dashboard starting on http://127.0.0.1:{port}")
    print(f"  Watching {len(TARGET_ZIP_CODES)} zip codes, max ${MAX_PURCHASE_PRICE:,}")
    app.run(host=host, port=port, debug=debug)
