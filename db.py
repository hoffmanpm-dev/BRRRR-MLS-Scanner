"""
BRRRR Dashboard - Listing History Database
Tracks listings over time to detect new listings and price changes.
"""

import os
import sqlite3
from datetime import datetime

DB_PATH = os.environ.get("BRRRR_DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "listing_history.db"))


def get_connection():
    """Get a SQLite connection with WAL mode for better concurrency."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """Create tables if they don't exist."""
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS listings (
            listing_id TEXT PRIMARY KEY,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            current_price REAL NOT NULL,
            original_price REAL NOT NULL,
            address TEXT,
            full_address TEXT,
            city TEXT,
            state TEXT,
            zip TEXT,
            neighborhood TEXT,
            beds INTEGER,
            baths INTEGER,
            sqft INTEGER,
            year_built INTEGER,
            status TEXT,
            score REAL,
            cashflow REAL,
            arv REAL,
            zillow_url TEXT,
            photo_url TEXT
        );

        CREATE TABLE IF NOT EXISTS price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            listing_id TEXT NOT NULL,
            price REAL NOT NULL,
            recorded_at TEXT NOT NULL,
            FOREIGN KEY (listing_id) REFERENCES listings(listing_id)
        );

        CREATE TABLE IF NOT EXISTS scan_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scanned_at TEXT NOT NULL,
            total_raw INTEGER,
            total_filtered INTEGER,
            total_viable INTEGER,
            new_listings INTEGER,
            price_changes INTEGER,
            email_sent INTEGER DEFAULT 0
        );
    """)
    conn.commit()
    conn.close()


def record_scan_results(scored_properties: list) -> dict:
    """
    Compare scored properties against history.
    Returns a dict with 'new', 'price_drops', 'price_increases', and 'unchanged' lists.
    """
    now = datetime.now().isoformat()
    conn = get_connection()

    new_listings = []
    price_drops = []
    price_increases = []
    unchanged = []

    for prop in scored_properties:
        listing_id = prop.get("id", "")
        price = prop.get("price", 0)

        existing = conn.execute(
            "SELECT listing_id, current_price, original_price FROM listings WHERE listing_id = ?",
            (listing_id,)
        ).fetchone()

        if existing is None:
            # New listing
            conn.execute("""
                INSERT INTO listings (
                    listing_id, first_seen, last_seen, current_price, original_price,
                    address, full_address, city, state, zip, neighborhood,
                    beds, baths, sqft, year_built, status, score, cashflow, arv,
                    zillow_url, photo_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                listing_id, now, now, price, price,
                prop.get("address"), prop.get("fullAddress"), prop.get("city"),
                prop.get("state"), prop.get("zip"), prop.get("neighborhood"),
                prop.get("beds"), prop.get("baths"), prop.get("sqft"),
                prop.get("yearBuilt"), prop.get("status"), prop.get("score"),
                prop.get("cashflow"), prop.get("arv"),
                prop.get("zillowUrl"), prop.get("photoUrl")
            ))
            conn.execute(
                "INSERT INTO price_history (listing_id, price, recorded_at) VALUES (?, ?, ?)",
                (listing_id, price, now)
            )
            new_listings.append(prop)

        else:
            old_price = existing["current_price"]

            # Update the listing record
            conn.execute("""
                UPDATE listings SET
                    last_seen = ?, current_price = ?, status = ?, score = ?,
                    cashflow = ?, arv = ?, address = ?, full_address = ?,
                    zillow_url = ?, photo_url = ?
                WHERE listing_id = ?
            """, (
                now, price, prop.get("status"), prop.get("score"),
                prop.get("cashflow"), prop.get("arv"), prop.get("address"),
                prop.get("fullAddress"), prop.get("zillowUrl"), prop.get("photoUrl"),
                listing_id
            ))

            if price < old_price:
                # Price drop
                conn.execute(
                    "INSERT INTO price_history (listing_id, price, recorded_at) VALUES (?, ?, ?)",
                    (listing_id, price, now)
                )
                prop["_old_price"] = old_price
                prop["_price_change"] = price - old_price
                prop["_price_change_pct"] = ((price - old_price) / old_price) * 100
                price_drops.append(prop)

            elif price > old_price:
                # Price increase
                conn.execute(
                    "INSERT INTO price_history (listing_id, price, recorded_at) VALUES (?, ?, ?)",
                    (listing_id, price, now)
                )
                prop["_old_price"] = old_price
                prop["_price_change"] = price - old_price
                prop["_price_change_pct"] = ((price - old_price) / old_price) * 100
                price_increases.append(prop)

            else:
                unchanged.append(prop)

    conn.commit()
    conn.close()

    return {
        "new": sorted(new_listings, key=lambda x: x.get("score", 0), reverse=True),
        "price_drops": sorted(price_drops, key=lambda x: x.get("_price_change", 0)),
        "price_increases": sorted(price_increases, key=lambda x: x.get("_price_change", 0), reverse=True),
        "unchanged": unchanged,
    }


def log_scan(total_raw, total_filtered, total_viable, new_count, price_change_count, email_sent=False):
    """Log a scan run for auditing."""
    conn = get_connection()
    conn.execute("""
        INSERT INTO scan_log (scanned_at, total_raw, total_filtered, total_viable, new_listings, price_changes, email_sent)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (datetime.now().isoformat(), total_raw, total_filtered, total_viable, new_count, price_change_count, int(email_sent)))
    conn.commit()
    conn.close()


def get_recent_scans(limit=10):
    """Get recent scan log entries."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM scan_log ORDER BY scanned_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_listing_history(listing_id):
    """Get price history for a specific listing."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT price, recorded_at FROM price_history WHERE listing_id = ? ORDER BY recorded_at",
        (listing_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# Initialize DB on import
init_db()
