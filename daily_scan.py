#!/usr/bin/env python3
"""
BRRRR Daily Scanner - Cron Job Entry Point
Runs a scan, compares against listing history, and emails the digest.

Usage:
    python daily_scan.py              # Full scan + email
    python daily_scan.py --dry-run    # Scan + preview email (no send)
    python daily_scan.py --test-email # Send a test email with current data
"""

import sys
from datetime import datetime
from scanner import run_scan
from emailer import send_email, build_email_html


def main():
    dry_run = "--dry-run" in sys.argv
    test_email = "--test-email" in sys.argv

    print("=" * 60)
    print(f"  BRRRR Daily Scanner — {datetime.now().strftime('%A, %B %d, %Y %I:%M %p')}")
    print("=" * 60)

    # Run the scan
    print("\n[1/2] Running MLS Grid scan...")
    scan_result = run_scan(track_changes=True)

    stats = scan_result["stats"]
    changes = scan_result.get("changes", {})
    print(f"\n  Results:")
    print(f"    Raw listings pulled:  {stats['totalRaw']}")
    print(f"    After filtering:      {stats['totalFiltered']}")
    print(f"    Viable BRRRR deals:   {stats['totalViable']}")
    print(f"    New listings:         {stats['newListings']}")
    print(f"    Price drops:          {stats['priceDrops']}")
    print(f"    Price increases:      {stats['priceIncreases']}")

    if scan_result["errors"]:
        print(f"\n  ⚠ Errors:")
        for e in scan_result["errors"]:
            print(f"    - {e}")

    # Send email
    has_changes = stats["newListings"] > 0 or stats["priceDrops"] > 0
    has_deals = stats["totalViable"] > 0

    if not has_deals and not has_changes:
        print("\n[2/2] No deals found and no changes — skipping email.")
        return

    print(f"\n[2/2] {'Building' if dry_run else 'Sending'} email digest...")
    success = send_email(scan_result, dry_run=dry_run)

    if success:
        if dry_run:
            print("\n  ✓ Dry run complete. Email preview saved to email_preview.html")
        else:
            print("\n  ✓ Email sent successfully!")
    else:
        print("\n  ✗ Email failed to send. Check SMTP_PASSWORD env var.")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("  Done!")
    print("=" * 60)


if __name__ == "__main__":
    main()
