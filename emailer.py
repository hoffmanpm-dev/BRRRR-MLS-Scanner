"""
BRRRR Dashboard - Email Digest
Sends daily HTML email reports via Gmail SMTP.
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

# ─── Email Config ─────────────────────────────────────────────────

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = os.environ.get("SMTP_USER", "hoffman.pm@gmail.com")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")  # Gmail App Password — set via env var

RECIPIENTS = [
    "paul@cophiaproperties.com",
    "katie@cophiaproperties.com",
]


def _format_price(amount):
    """Format a number as $XXX,XXX."""
    return f"${amount:,.0f}" if amount else "$0"


def _format_pct(pct):
    """Format a percentage."""
    return f"{pct:+.1f}%" if pct else "0%"


def _score_color(score):
    """Return a hex color based on BRRRR score."""
    if score >= 60:
        return "#00d68f"  # green
    elif score >= 40:
        return "#ffd93d"  # yellow
    else:
        return "#ff6b6b"  # red


def _build_property_row(prop, label=None, label_color="#6c5ce7"):
    """Build an HTML table row for a single property."""
    score = prop.get("score", 0)
    price_note = ""
    if prop.get("_old_price"):
        old = prop["_old_price"]
        change = prop["_price_change"]
        pct = prop["_price_change_pct"]
        direction = "▼" if change < 0 else "▲"
        color = "#00d68f" if change < 0 else "#ff6b6b"
        price_note = f'<br><span style="color:{color};font-size:12px;">{direction} {_format_price(abs(change))} ({pct:+.1f}%) from {_format_price(old)}</span>'

    label_html = ""
    if label:
        label_html = f'<span style="background:{label_color};color:#fff;padding:2px 8px;border-radius:3px;font-size:11px;font-weight:600;margin-right:6px;">{label}</span>'

    return f"""
    <tr style="border-bottom:1px solid #eee;">
        <td style="padding:12px 8px;vertical-align:top;">
            {label_html}
            <strong><a href="{prop.get('zillowUrl', '#')}" style="color:#2c3e50;text-decoration:none;">{prop.get('address', 'N/A')}</a></strong>
            <br><span style="color:#888;font-size:12px;">{prop.get('city', '')}, {prop.get('state', '')} {prop.get('zip', '')} — {prop.get('neighborhood', '')}</span>
        </td>
        <td style="padding:12px 8px;text-align:right;vertical-align:top;">
            <strong>{_format_price(prop.get('price', 0))}</strong>
            {price_note}
        </td>
        <td style="padding:12px 8px;text-align:center;vertical-align:top;">
            {prop.get('beds', 0)}bd / {prop.get('baths', 0)}ba
            <br><span style="color:#888;font-size:12px;">{prop.get('sqft', 0):,} sqft</span>
        </td>
        <td style="padding:12px 8px;text-align:center;vertical-align:top;">
            <span style="color:{_score_color(score)};font-weight:700;font-size:16px;">{score}</span>
        </td>
        <td style="padding:12px 8px;text-align:right;vertical-align:top;">
            <span style="color:{'#00d68f' if prop.get('cashflow', 0) > 0 else '#ff6b6b'};font-weight:600;">{_format_price(prop.get('cashflow', 0))}/mo</span>
            <br><span style="color:#888;font-size:12px;">Cap: {prop.get('capRate', 0):.1f}%</span>
        </td>
        <td style="padding:12px 8px;text-align:center;vertical-align:top;">
            <a href="{prop.get('zillowUrl', '#')}" style="background:#6c5ce7;color:#fff;padding:6px 12px;border-radius:4px;text-decoration:none;font-size:12px;">View</a>
        </td>
    </tr>
    """


def build_email_html(scan_result: dict) -> str:
    """Build a complete HTML email from scan results."""
    changes = scan_result.get("changes", {})
    stats = scan_result.get("stats", {})
    now = datetime.now()

    new_listings = changes.get("new", []) if changes else []
    price_drops = changes.get("price_drops", []) if changes else []
    price_increases = changes.get("price_increases", []) if changes else []
    all_properties = scan_result.get("properties", [])

    # Summary counts
    new_count = len(new_listings)
    drop_count = len(price_drops)
    increase_count = len(price_increases)
    total = stats.get("totalViable", len(all_properties))

    # Build sections
    sections_html = ""

    # New Listings
    if new_listings:
        rows = "".join(_build_property_row(p, label="NEW", label_color="#00d68f") for p in new_listings[:15])
        sections_html += f"""
        <h2 style="color:#00d68f;border-bottom:2px solid #00d68f;padding-bottom:8px;margin-top:32px;">
            🏠 {new_count} New Listing{'s' if new_count != 1 else ''}
        </h2>
        <table style="width:100%;border-collapse:collapse;font-size:14px;">
            <tr style="background:#f8f9fa;border-bottom:2px solid #dee2e6;">
                <th style="padding:8px;text-align:left;">Property</th>
                <th style="padding:8px;text-align:right;">Price</th>
                <th style="padding:8px;text-align:center;">Size</th>
                <th style="padding:8px;text-align:center;">Score</th>
                <th style="padding:8px;text-align:right;">Cashflow</th>
                <th style="padding:8px;text-align:center;">Link</th>
            </tr>
            {rows}
        </table>
        """

    # Price Drops
    if price_drops:
        rows = "".join(_build_property_row(p, label="PRICE DROP", label_color="#e67e22") for p in price_drops[:10])
        sections_html += f"""
        <h2 style="color:#e67e22;border-bottom:2px solid #e67e22;padding-bottom:8px;margin-top:32px;">
            📉 {drop_count} Price Drop{'s' if drop_count != 1 else ''}
        </h2>
        <table style="width:100%;border-collapse:collapse;font-size:14px;">
            <tr style="background:#f8f9fa;border-bottom:2px solid #dee2e6;">
                <th style="padding:8px;text-align:left;">Property</th>
                <th style="padding:8px;text-align:right;">Price</th>
                <th style="padding:8px;text-align:center;">Size</th>
                <th style="padding:8px;text-align:center;">Score</th>
                <th style="padding:8px;text-align:right;">Cashflow</th>
                <th style="padding:8px;text-align:center;">Link</th>
            </tr>
            {rows}
        </table>
        """

    # Price Increases (brief mention)
    if price_increases:
        rows = "".join(_build_property_row(p, label="PRICE UP", label_color="#95a5a6") for p in price_increases[:5])
        sections_html += f"""
        <h2 style="color:#95a5a6;border-bottom:2px solid #95a5a6;padding-bottom:8px;margin-top:32px;">
            📈 {increase_count} Price Increase{'s' if increase_count != 1 else ''}
        </h2>
        <table style="width:100%;border-collapse:collapse;font-size:14px;">
            <tr style="background:#f8f9fa;border-bottom:2px solid #dee2e6;">
                <th style="padding:8px;text-align:left;">Property</th>
                <th style="padding:8px;text-align:right;">Price</th>
                <th style="padding:8px;text-align:center;">Size</th>
                <th style="padding:8px;text-align:center;">Score</th>
                <th style="padding:8px;text-align:right;">Cashflow</th>
                <th style="padding:8px;text-align:center;">Link</th>
            </tr>
            {rows}
        </table>
        """

    # Top 10 overall (if no changes to show)
    if not new_listings and not price_drops and not price_increases:
        top = all_properties[:10]
        if top:
            rows = "".join(_build_property_row(p) for p in top)
            sections_html += f"""
            <h2 style="color:#6c5ce7;border-bottom:2px solid #6c5ce7;padding-bottom:8px;margin-top:32px;">
                🏆 Top 10 Deals (No Changes Today)
            </h2>
            <table style="width:100%;border-collapse:collapse;font-size:14px;">
                <tr style="background:#f8f9fa;border-bottom:2px solid #dee2e6;">
                    <th style="padding:8px;text-align:left;">Property</th>
                    <th style="padding:8px;text-align:right;">Price</th>
                    <th style="padding:8px;text-align:center;">Size</th>
                    <th style="padding:8px;text-align:center;">Score</th>
                    <th style="padding:8px;text-align:right;">Cashflow</th>
                    <th style="padding:8px;text-align:center;">Link</th>
                </tr>
                {rows}
            </table>
            """
        else:
            sections_html += """
            <p style="color:#888;font-size:16px;text-align:center;padding:40px;">
                No viable BRRRR deals found in your target zip codes today.
            </p>
            """

    # No-changes fallback message
    if not new_listings and not price_drops and not price_increases and all_properties:
        sections_html = f"""
        <div style="background:#f0f0f0;border-radius:8px;padding:16px;margin:20px 0;text-align:center;">
            <p style="color:#666;margin:0;">No new listings or price changes since the last scan. Here are your top current deals:</p>
        </div>
        """ + sections_html

    # Zip code summary
    from config import TARGET_ZIP_CODES
    zip_summary = " · ".join(f"{z} ({name})" for z, name in TARGET_ZIP_CODES.items())

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:800px;margin:0 auto;padding:20px;color:#2c3e50;background:#ffffff;">

    <div style="background:linear-gradient(135deg,#6c5ce7,#a29bfe);padding:24px 32px;border-radius:12px;margin-bottom:24px;">
        <h1 style="color:#fff;margin:0 0 8px 0;font-size:24px;">BRRRR Deal Scanner</h1>
        <p style="color:rgba(255,255,255,0.85);margin:0;font-size:14px;">
            Daily Digest — {now.strftime('%A, %B %d, %Y')}
        </p>
    </div>

    <div style="display:flex;gap:12px;margin-bottom:24px;flex-wrap:wrap;">
        <div style="background:#f8f9fa;border-radius:8px;padding:12px 20px;flex:1;min-width:120px;text-align:center;">
            <div style="font-size:24px;font-weight:700;color:#00d68f;">{new_count}</div>
            <div style="font-size:12px;color:#888;">New Listings</div>
        </div>
        <div style="background:#f8f9fa;border-radius:8px;padding:12px 20px;flex:1;min-width:120px;text-align:center;">
            <div style="font-size:24px;font-weight:700;color:#e67e22;">{drop_count}</div>
            <div style="font-size:12px;color:#888;">Price Drops</div>
        </div>
        <div style="background:#f8f9fa;border-radius:8px;padding:12px 20px;flex:1;min-width:120px;text-align:center;">
            <div style="font-size:24px;font-weight:700;color:#6c5ce7;">{total}</div>
            <div style="font-size:12px;color:#888;">Total Deals</div>
        </div>
    </div>

    {sections_html}

    <hr style="border:none;border-top:1px solid #eee;margin:32px 0 16px 0;">
    <p style="color:#aaa;font-size:11px;text-align:center;">
        BRRRR Deal Scanner · Watching: {zip_summary}<br>
        Max price: {_format_price(scan_result.get('criteria', {}).get('maxPrice', 0))} ·
        Min cashflow: {_format_price(scan_result.get('criteria', {}).get('minCashflow', 0))}/mo ·
        Refi rate: {scan_result.get('criteria', {}).get('refiRate', 0):.1f}%
    </p>

</body>
</html>"""

    return html


def send_email(scan_result: dict, recipients: list = None, dry_run: bool = False) -> bool:
    """
    Build and send the daily digest email.
    Returns True if sent successfully.
    """
    if not SMTP_PASSWORD:
        print("[EMAIL] ERROR: SMTP_PASSWORD not set. Cannot send email.")
        print("[EMAIL] Set the SMTP_PASSWORD environment variable with your Gmail App Password.")
        return False

    recipients = recipients or RECIPIENTS
    html = build_email_html(scan_result)

    changes = scan_result.get("changes", {})
    new_count = len(changes.get("new", [])) if changes else 0
    drop_count = len(changes.get("price_drops", [])) if changes else 0
    total = scan_result.get("stats", {}).get("totalViable", 0)

    # Build a descriptive subject line
    parts = []
    if new_count:
        parts.append(f"{new_count} new")
    if drop_count:
        parts.append(f"{drop_count} price drop{'s' if drop_count != 1 else ''}")
    if parts:
        subject = f"BRRRR Scanner: {', '.join(parts)} — {datetime.now().strftime('%m/%d')}"
    else:
        subject = f"BRRRR Scanner: {total} active deals — {datetime.now().strftime('%m/%d')}"

    if dry_run:
        print(f"[EMAIL] DRY RUN — would send to {recipients}")
        print(f"[EMAIL] Subject: {subject}")
        print(f"[EMAIL] HTML length: {len(html)} chars")
        # Save HTML preview
        with open("email_preview.html", "w") as f:
            f.write(html)
        print("[EMAIL] Preview saved to email_preview.html")
        return True

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"BRRRR Scanner <{SMTP_USER}>"
    msg["To"] = ", ".join(recipients)

    # Plain text fallback
    plain = f"BRRRR Daily Digest — {new_count} new listings, {drop_count} price drops, {total} total deals. View the full report in an HTML-capable email client."
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))

    try:
        print(f"[EMAIL] Connecting to {SMTP_HOST}:{SMTP_PORT}...")
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, recipients, msg.as_string())
        print(f"[EMAIL] Sent to {', '.join(recipients)}")
        return True
    except Exception as e:
        print(f"[EMAIL] Failed to send: {e}")
        return False
