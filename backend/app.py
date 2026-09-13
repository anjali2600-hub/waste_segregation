"""
Waste Segregation — behaviour-first bridge to waste segregation at the source.

Single Flask app that:
  * serves the JSON REST API under /api/...
  * serves the static frontend (plain HTML/CSS/JS, no build step) so the
    whole prototype runs with a single `python app.py`.

See README.md at the project root for setup, demo accounts and the
step-by-step live-demo script.
"""
import os
import sqlite3
from datetime import date, datetime, timedelta

from flask import Flask, jsonify, request, g, send_from_directory

import config
import db as dbmod
from auth import (
    hash_password, verify_password, issue_token, login_required, require_role,
)

FRONTEND_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "frontend")
)

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")


# ---------------------------------------------------------------------------
# CORS (harmless even when frontend is served from the same origin; keeps
# the API usable if someone points a separate dev server at it).
# ---------------------------------------------------------------------------
@app.after_request
def add_cors_headers(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    return resp


@app.route("/api/<path:_any>", methods=["OPTIONS"])
def cors_preflight(_any):
    return "", 204


# ---------------------------------------------------------------------------
# Startup: create tables, seed demo data on first run (or if RESEED_ON_START)
# ---------------------------------------------------------------------------
def bootstrap():
    dbmod.init_db(app)
    conn = sqlite3.connect(config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    needs_seed = config.RESEED_ON_START
    if not needs_seed:
        count = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        needs_seed = count == 0
    if needs_seed:
        import seed
        seed.run_seed(conn)
        print("[Waste Segregation] Database seeded with demo data.")
    conn.close()


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def credit_rules_map(db):
    return {r["rating"]: r["credits"] for r in db.execute("SELECT rating, credits FROM credit_rules")}


def get_household_or_404(db, code):
    return db.execute(
        "SELECT h.*, w.ward_name, w.city FROM households h "
        "LEFT JOIN wards w ON w.id = h.ward_id WHERE h.household_code = ?",
        (code,),
    ).fetchone()


def household_balance(db, household_id):
    row = db.execute(
        "SELECT COALESCE(SUM(amount), 0) AS bal FROM green_credit_transactions WHERE household_id = ?",
        (household_id,),
    ).fetchone()
    return row["bal"]


def assert_household_access(household_row):
    """Household users may only access their own record; admin sees all."""
    user = g.current_user
    if user["role"] == "ADMIN":
        return True
    if user["role"] == "HOUSEHOLD" and household_row["user_id"] == user["id"]:
        return True
    return False


# ===========================================================================
# AUTH
# ===========================================================================
@app.post("/api/auth/login")
def login():
    data = request.get_json(silent=True) or {}
    contact = (data.get("contact") or "").strip()
    password = data.get("password") or ""
    if not contact or not password:
        return jsonify(error="contact and password are required"), 400

    db = dbmod.get_db()
    user = db.execute("SELECT * FROM users WHERE contact = ?", (contact,)).fetchone()
    if not user or not verify_password(password, user["password_hash"]):
        return jsonify(error="Invalid credentials"), 401

    token = issue_token(user)
    profile = {}
    if user["role"] == "HOUSEHOLD":
        hh = db.execute("SELECT household_code FROM households WHERE user_id = ?", (user["id"],)).fetchone()
        if hh:
            profile["household_code"] = hh["household_code"]
    elif user["role"] == "COLLECTOR":
        c = db.execute("SELECT collector_code FROM collectors WHERE user_id = ?", (user["id"],)).fetchone()
        if c:
            profile["collector_code"] = c["collector_code"]

    return jsonify(
        token=token,
        role=user["role"],
        user={"id": user["id"], "name": user["name"], "contact": user["contact"]},
        profile=profile,
    )


@app.post("/api/auth/register")
def register():
    """Self-service registration -- household applicants only.

    (Collectors and admins are provisioned by an existing admin, matching
    the real-world ULB workflow -- see /api/admin/collectors.)
    """
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    contact = (data.get("contact") or "").strip()
    password = data.get("password") or ""
    address = (data.get("address") or "").strip()
    ward_id = data.get("ward_id")

    if not name or not contact or not password or not ward_id:
        return jsonify(error="name, contact, password and ward_id are required"), 400
    if len(password) < 6:
        return jsonify(error="password must be at least 6 characters"), 400

    db = dbmod.get_db()
    ward = db.execute("SELECT * FROM wards WHERE id = ?", (ward_id,)).fetchone()
    if not ward:
        return jsonify(error="Invalid ward_id"), 400
    if db.execute("SELECT 1 FROM users WHERE contact = ?", (contact,)).fetchone():
        return jsonify(error="An account with this contact already exists"), 409

    cur = db.cursor()
    cur.execute(
        "INSERT INTO users (name, contact, password_hash, role) VALUES (?, ?, ?, 'HOUSEHOLD')",
        (name, contact, hash_password(password)),
    )
    user_id = cur.lastrowid

    next_num = db.execute(
        "SELECT COALESCE(MAX(CAST(SUBSTR(household_code, 3) AS INTEGER)), 10000) + 1 AS n FROM households"
    ).fetchone()["n"]
    code = f"H-{next_num}"
    qr_payload = f"WASTESEG:{code}"

    cur.execute(
        "INSERT INTO households (household_code, address, ward_id, district, qr_code, user_id) "
        "VALUES (?, ?, ?, 'Raipur', ?, ?)",
        (code, address, ward_id, qr_payload, user_id),
    )
    db.execute("UPDATE wards SET total_households = total_households + 1 WHERE id = ?", (ward_id,))
    db.commit()

    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    token = issue_token(user)
    return jsonify(
        token=token, role="HOUSEHOLD",
        user={"id": user_id, "name": name, "contact": contact},
        profile={"household_code": code},
    ), 201


@app.get("/api/auth/me")
@login_required
def me():
    return jsonify(user=g.current_user)


@app.get("/api/wards")
def list_wards_public():
    """Public endpoint (needed by the registration form's ward dropdown)."""
    db = dbmod.get_db()
    rows = db.execute("SELECT id, ward_name, city FROM wards ORDER BY ward_name").fetchall()
    return jsonify(wards=dbmod.rows_to_list(rows))


# ===========================================================================
# HOUSEHOLD
# ===========================================================================
@app.get("/api/households/<code>")
@login_required
def get_household(code):
    db = dbmod.get_db()
    hh = get_household_or_404(db, code)
    if not hh:
        return jsonify(error="Household not found"), 404
    if not assert_household_access(hh):
        return jsonify(error="Forbidden"), 403

    balance = household_balance(db, hh["id"])
    today = date.today().isoformat()
    today_collection = db.execute(
        "SELECT * FROM collections WHERE household_id = ? AND collection_date = ?",
        (hh["id"], today),
    ).fetchone()

    return jsonify(
        household_code=hh["household_code"],
        address=hh["address"],
        ward=hh["ward_name"],
        city=hh["city"],
        district=hh["district"],
        credit_balance=balance,
        today_status=today_collection["rating"] if today_collection else "NOT_RATED",
        member_since=hh["created_at"],
    )


@app.get("/api/households/<code>/qr")
@login_required
def get_household_qr(code):
    db = dbmod.get_db()
    hh = get_household_or_404(db, code)
    if not hh:
        return jsonify(error="Household not found"), 404
    if not assert_household_access(hh):
        return jsonify(error="Forbidden"), 403
    return jsonify(household_code=hh["household_code"], qr_payload=hh["qr_code"])


@app.get("/api/households/<code>/history")
@login_required
def get_household_history(code):
    db = dbmod.get_db()
    hh = get_household_or_404(db, code)
    if not hh:
        return jsonify(error="Household not found"), 404
    if not assert_household_access(hh):
        return jsonify(error="Forbidden"), 403

    limit = min(int(request.args.get("limit", 60)), 200)
    rows = db.execute(
        "SELECT c.collection_date, c.rating, c.credits_awarded, c.timestamp, "
        "col.name AS collector_name, col.collector_code "
        "FROM collections c JOIN collectors col ON col.id = c.collector_id "
        "WHERE c.household_id = ? ORDER BY c.collection_date DESC LIMIT ?",
        (hh["id"], limit),
    ).fetchall()
    return jsonify(history=dbmod.rows_to_list(rows))


@app.get("/api/households/<code>/credits")
@login_required
def get_household_credits(code):
    db = dbmod.get_db()
    hh = get_household_or_404(db, code)
    if not hh:
        return jsonify(error="Household not found"), 404
    if not assert_household_access(hh):
        return jsonify(error="Forbidden"), 403

    balance = household_balance(db, hh["id"])
    txns = db.execute(
        "SELECT amount, transaction_type, description, timestamp "
        "FROM green_credit_transactions WHERE household_id = ? ORDER BY timestamp DESC LIMIT 100",
        (hh["id"],),
    ).fetchall()
    return jsonify(balance=balance, transactions=dbmod.rows_to_list(txns))


@app.get("/api/households/<code>/summary")
@login_required
def get_household_summary(code):
    """Dashboard aggregate: monthly performance + rating breakdown."""
    db = dbmod.get_db()
    hh = get_household_or_404(db, code)
    if not hh:
        return jsonify(error="Household not found"), 404
    if not assert_household_access(hh):
        return jsonify(error="Forbidden"), 403

    since = (date.today() - timedelta(days=30)).isoformat()
    rows = db.execute(
        "SELECT rating, COUNT(*) AS n FROM collections "
        "WHERE household_id = ? AND collection_date >= ? GROUP BY rating",
        (hh["id"], since),
    ).fetchall()
    breakdown = {"GOOD": 0, "AVERAGE": 0, "POOR": 0}
    for r in rows:
        breakdown[r["rating"]] = r["n"]
    total = sum(breakdown.values())
    segregation_rate = round((breakdown["GOOD"] / total) * 100, 1) if total else 0.0

    return jsonify(
        household_code=hh["household_code"],
        last_30_days=breakdown,
        total_collections_30d=total,
        segregation_rate_30d=segregation_rate,
        credit_balance=household_balance(db, hh["id"]),
    )


@app.get("/api/households/<code>/redemptions")
@login_required
def get_household_redemptions(code):
    db = dbmod.get_db()
    hh = get_household_or_404(db, code)
    if not hh:
        return jsonify(error="Household not found"), 404
    if not assert_household_access(hh):
        return jsonify(error="Forbidden"), 403
    rows = db.execute(
        "SELECT r.redemption_date, r.credits_used, r.status, rw.name AS reward_name "
        "FROM redemptions r JOIN rewards rw ON rw.id = r.reward_id "
        "WHERE r.household_id = ? ORDER BY r.redemption_date DESC",
        (hh["id"],),
    ).fetchall()
    return jsonify(redemptions=dbmod.rows_to_list(rows))


# ===========================================================================
# COLLECTOR
# ===========================================================================
def get_collector_for_user(db, user_id):
    return db.execute("SELECT * FROM collectors WHERE user_id = ?", (user_id,)).fetchone()


@app.get("/api/collector/lookup")
@require_role("COLLECTOR", "ADMIN")
def collector_lookup():
    """Resolve a scanned QR payload or manually-entered household code.

    Accepts either the raw code (H-10023) or the full QR payload
    (WASTESEG:H-10023).
    """
    raw = (request.args.get("code") or "").strip().upper()
    if not raw:
        return jsonify(error="code query parameter is required"), 400
    code = raw.split("WASTESEG:")[-1] if "WASTESEG:" in raw else raw

    db = dbmod.get_db()
    hh = get_household_or_404(db, code)
    if not hh:
        return jsonify(error=f"No household found for code '{code}'"), 404

    today = date.today().isoformat()
    today_collection = db.execute(
        "SELECT * FROM collections WHERE household_id = ? AND collection_date = ?",
        (hh["id"], today),
    ).fetchone()

    return jsonify(
        household_code=hh["household_code"],
        address=hh["address"],
        ward=hh["ward_name"],
        today_status=today_collection["rating"] if today_collection else "NOT_RATED",
        already_rated_today=today_collection is not None,
    )


@app.get("/api/collector/today")
@require_role("COLLECTOR", "ADMIN")
def collector_today():
    db = dbmod.get_db()
    collector = get_collector_for_user(db, g.current_user["id"])
    if not collector and g.current_user["role"] != "ADMIN":
        return jsonify(error="No collector profile for this user"), 404

    today = date.today().isoformat()

    if collector:
        ward_id = collector["ward_id"]
        households = db.execute(
            "SELECT h.household_code, h.address, "
            "c.rating, c.credits_awarded "
            "FROM households h "
            "LEFT JOIN collections c ON c.household_id = h.id AND c.collection_date = ? "
            "WHERE h.ward_id = ? ORDER BY h.household_code",
            (today, ward_id),
        ).fetchall()
        rated = sum(1 for r in households if r["rating"] is not None)
        return jsonify(
            collector_code=collector["collector_code"],
            date=today,
            total_assigned=len(households),
            rated_today=rated,
            pending_today=len(households) - rated,
            households=dbmod.rows_to_list(households),
        )

    return jsonify(error="Admin should use /api/admin/collections"), 400


@app.post("/api/collections")
@require_role("COLLECTOR", "ADMIN")
def submit_collection():
    data = request.get_json(silent=True) or {}
    code = (data.get("household_code") or "").strip().upper().split("WASTESEG:")[-1]
    rating = (data.get("rating") or "").strip().upper()

    if not code or rating not in config.RATINGS:
        return jsonify(error="household_code and a valid rating (GOOD/AVERAGE/POOR) are required"), 400

    db = dbmod.get_db()
    hh = get_household_or_404(db, code)
    if not hh:
        return jsonify(error=f"No household found for code '{code}'"), 404

    collector = get_collector_for_user(db, g.current_user["id"])
    if not collector:
        if g.current_user["role"] == "ADMIN":
            return jsonify(error="Admin accounts cannot submit ratings; use a collector account"), 400
        return jsonify(error="No collector profile for this user"), 404

    rules = credit_rules_map(db)
    credits = rules.get(rating, 0)
    today = date.today().isoformat()

    existing = db.execute(
        "SELECT * FROM collections WHERE household_id = ? AND collection_date = ?",
        (hh["id"], today),
    ).fetchone()

    cur = db.cursor()
    if existing:
        # Business rule: duplicate same-day submissions are treated as a
        # correction rather than a silent error or a duplicate ledger entry.
        cur.execute(
            "UPDATE collections SET rating = ?, credits_awarded = ?, collector_id = ?, "
            "timestamp = datetime('now') WHERE id = ?",
            (rating, credits, collector["id"], existing["id"]),
        )
        cur.execute("DELETE FROM green_credit_transactions WHERE collection_id = ?", (existing["id"],))
        collection_id = existing["id"]
        was_correction = True
    else:
        cur.execute(
            "INSERT INTO collections (household_id, collector_id, rating, credits_awarded, collection_date) "
            "VALUES (?, ?, ?, ?, ?)",
            (hh["id"], collector["id"], rating, credits, today),
        )
        collection_id = cur.lastrowid
        was_correction = False

    if credits > 0:
        cur.execute(
            "INSERT INTO green_credit_transactions "
            "(household_id, collection_id, amount, transaction_type, description) "
            "VALUES (?, ?, ?, 'EARNED', ?)",
            (hh["id"], collection_id, credits,
             f"Collection rated {rating.title()} on {today} by {collector['collector_code']}"),
        )
    db.commit()

    new_balance = household_balance(db, hh["id"])
    return jsonify(
        success=True,
        corrected=was_correction,
        household_code=hh["household_code"],
        rating=rating,
        credits_awarded=credits,
        new_balance=new_balance,
        message=f"Collection recorded successfully. +{credits} Green Credits awarded."
                if credits > 0 else "Collection recorded. No credits awarded for this rating.",
    ), 201 if not was_correction else 200


# ===========================================================================
# REWARDS
# ===========================================================================
@app.get("/api/rewards")
@login_required
def list_rewards():
    db = dbmod.get_db()
    rows = db.execute("SELECT * FROM rewards WHERE available = 1 ORDER BY credits_required").fetchall()
    return jsonify(rewards=dbmod.rows_to_list(rows))


@app.post("/api/rewards/redeem")
@require_role("HOUSEHOLD")
def redeem_reward():
    data = request.get_json(silent=True) or {}
    reward_id = data.get("reward_id")
    if not reward_id:
        return jsonify(error="reward_id is required"), 400

    db = dbmod.get_db()
    hh = db.execute("SELECT * FROM households WHERE user_id = ?", (g.current_user["id"],)).fetchone()
    if not hh:
        return jsonify(error="No household profile for this user"), 404

    reward = db.execute("SELECT * FROM rewards WHERE id = ? AND available = 1", (reward_id,)).fetchone()
    if not reward:
        return jsonify(error="Reward not found or unavailable"), 404

    balance = household_balance(db, hh["id"])
    if balance < reward["credits_required"]:
        return jsonify(error=f"Insufficient credits. Balance {balance}, need {reward['credits_required']}"), 400

    cur = db.cursor()
    cur.execute(
        "INSERT INTO redemptions (household_id, reward_id, credits_used, status) VALUES (?, ?, ?, 'COMPLETED')",
        (hh["id"], reward_id, reward["credits_required"]),
    )
    cur.execute(
        "INSERT INTO green_credit_transactions (household_id, amount, transaction_type, description) "
        "VALUES (?, ?, 'REDEEMED', ?)",
        (hh["id"], -reward["credits_required"], f"Redeemed: {reward['name']} (prototype/mock fulfilment)"),
    )
    db.commit()

    return jsonify(
        success=True,
        reward=reward["name"],
        credits_used=reward["credits_required"],
        new_balance=household_balance(db, hh["id"]),
        note="Prototype mock redemption -- not connected to a real property-tax, "
             "electricity-bill or shop-partner system.",
    ), 201


# ===========================================================================
# ADMIN
# ===========================================================================
@app.get("/api/admin/dashboard")
@require_role("ADMIN")
def admin_dashboard():
    db = dbmod.get_db()
    today = date.today().isoformat()

    total_households = db.execute("SELECT COUNT(*) c FROM households").fetchone()["c"]
    total_collectors = db.execute("SELECT COUNT(*) c FROM collectors").fetchone()["c"]
    today_collections = db.execute(
        "SELECT COUNT(*) c FROM collections WHERE collection_date = ?", (today,)
    ).fetchone()["c"]
    active_households = db.execute(
        "SELECT COUNT(DISTINCT household_id) c FROM collections "
        "WHERE collection_date >= date('now', '-30 day')"
    ).fetchone()["c"]
    total_credits_issued = db.execute(
        "SELECT COALESCE(SUM(amount), 0) s FROM green_credit_transactions WHERE transaction_type = 'EARNED'"
    ).fetchone()["s"]

    rating_dist_rows = db.execute(
        "SELECT rating, COUNT(*) c FROM collections WHERE collection_date >= date('now', '-30 day') GROUP BY rating"
    ).fetchall()
    rating_distribution = {"GOOD": 0, "AVERAGE": 0, "POOR": 0}
    for r in rating_dist_rows:
        rating_distribution[r["rating"]] = r["c"]
    total_rated_30d = sum(rating_distribution.values())
    segregation_rate = round((rating_distribution["GOOD"] / total_rated_30d) * 100, 1) if total_rated_30d else 0.0

    return jsonify(
        total_households=total_households,
        active_households_30d=active_households,
        total_collectors=total_collectors,
        todays_collections=today_collections,
        segregation_rate_30d=segregation_rate,
        total_green_credits_issued=total_credits_issued,
        rating_distribution_30d=rating_distribution,
    )


@app.get("/api/admin/wards")
@require_role("ADMIN")
def admin_wards():
    db = dbmod.get_db()
    wards = db.execute("SELECT * FROM wards ORDER BY ward_name").fetchall()
    result = []
    for w in wards:
        stats = db.execute(
            "SELECT "
            "  COUNT(*) AS total, "
            "  SUM(CASE WHEN c.rating='GOOD' THEN 1 ELSE 0 END) AS good, "
            "  SUM(CASE WHEN c.rating='AVERAGE' THEN 1 ELSE 0 END) AS average, "
            "  SUM(CASE WHEN c.rating='POOR' THEN 1 ELSE 0 END) AS poor "
            "FROM collections c JOIN households h ON h.id = c.household_id "
            "WHERE h.ward_id = ? AND c.collection_date >= date('now', '-30 day')",
            (w["id"],),
        ).fetchone()
        total = stats["total"] or 0
        good = stats["good"] or 0
        average = stats["average"] or 0
        poor = stats["poor"] or 0
        result.append({
            "ward_id": w["id"],
            "ward_name": w["ward_name"],
            "city": w["city"],
            "households": w["total_households"],
            "collections_30d": total,
            "good_pct": round(good / total * 100, 1) if total else 0.0,
            "average_pct": round(average / total * 100, 1) if total else 0.0,
            "poor_pct": round(poor / total * 100, 1) if total else 0.0,
        })
    return jsonify(wards=result)


@app.get("/api/admin/analytics")
@require_role("ADMIN")
def admin_analytics():
    db = dbmod.get_db()

    # Daily trend, last 14 days
    daily_rows = db.execute(
        "SELECT collection_date, "
        "  SUM(CASE WHEN rating='GOOD' THEN 1 ELSE 0 END) AS good, "
        "  SUM(CASE WHEN rating='AVERAGE' THEN 1 ELSE 0 END) AS average, "
        "  SUM(CASE WHEN rating='POOR' THEN 1 ELSE 0 END) AS poor, "
        "  COUNT(*) AS total "
        "FROM collections WHERE collection_date >= date('now', '-14 day') "
        "GROUP BY collection_date ORDER BY collection_date"
    ).fetchall()
    daily_trend = [{
        "date": r["collection_date"],
        "good": r["good"], "average": r["average"], "poor": r["poor"],
        "segregation_rate": round(r["good"] / r["total"] * 100, 1) if r["total"] else 0,
    } for r in daily_rows]

    # Weekly trend, last 8 weeks (grouped by ISO week via strftime)
    weekly_rows = db.execute(
        "SELECT strftime('%Y-W%W', collection_date) AS wk, "
        "  SUM(CASE WHEN rating='GOOD' THEN 1 ELSE 0 END) AS good, COUNT(*) AS total "
        "FROM collections WHERE collection_date >= date('now', '-56 day') "
        "GROUP BY wk ORDER BY wk"
    ).fetchall()
    weekly_trend = [{
        "week": r["wk"], "total": r["total"],
        "segregation_rate": round(r["good"] / r["total"] * 100, 1) if r["total"] else 0,
    } for r in weekly_rows]

    # Top households (by credits earned)
    top_households = db.execute(
        "SELECT h.household_code, w.ward_name, COALESCE(SUM(t.amount), 0) AS credits "
        "FROM households h LEFT JOIN green_credit_transactions t ON t.household_id = h.id "
        "AND t.transaction_type = 'EARNED' "
        "LEFT JOIN wards w ON w.id = h.ward_id "
        "GROUP BY h.id ORDER BY credits DESC LIMIT 10"
    ).fetchall()

    # Top wards (by segregation rate, min 5 collections)
    top_wards = db.execute(
        "SELECT w.ward_name, COUNT(*) AS total, "
        "  SUM(CASE WHEN c.rating='GOOD' THEN 1 ELSE 0 END) AS good "
        "FROM collections c JOIN households h ON h.id = c.household_id "
        "JOIN wards w ON w.id = h.ward_id "
        "WHERE c.collection_date >= date('now', '-30 day') "
        "GROUP BY w.id HAVING total >= 5 "
        "ORDER BY (good * 1.0 / total) DESC LIMIT 10"
    ).fetchall()

    return jsonify(
        daily_trend=daily_trend,
        weekly_trend=weekly_trend,
        top_households=dbmod.rows_to_list(top_households),
        top_wards=[{
            "ward_name": r["ward_name"],
            "total_collections": r["total"],
            "segregation_rate": round(r["good"] / r["total"] * 100, 1) if r["total"] else 0,
        } for r in top_wards],
    )


@app.get("/api/admin/households")
@require_role("ADMIN")
def admin_list_households():
    db = dbmod.get_db()
    ward_id = request.args.get("ward_id")
    q = "SELECT h.*, w.ward_name FROM households h LEFT JOIN wards w ON w.id = h.ward_id"
    params = []
    if ward_id:
        q += " WHERE h.ward_id = ?"
        params.append(ward_id)
    q += " ORDER BY h.household_code"
    rows = db.execute(q, params).fetchall()
    out = []
    for r in rows:
        out.append({
            "household_code": r["household_code"], "address": r["address"],
            "ward": r["ward_name"], "district": r["district"],
            "credit_balance": household_balance(db, r["id"]),
            "created_at": r["created_at"],
        })
    return jsonify(households=out)


@app.post("/api/admin/households")
@require_role("ADMIN")
def admin_add_household():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    contact = (data.get("contact") or "").strip()
    password = data.get("password") or "house123"
    address = (data.get("address") or "").strip()
    ward_id = data.get("ward_id")

    if not name or not contact or not ward_id:
        return jsonify(error="name, contact and ward_id are required"), 400

    db = dbmod.get_db()
    if db.execute("SELECT 1 FROM users WHERE contact = ?", (contact,)).fetchone():
        return jsonify(error="An account with this contact already exists"), 409
    ward = db.execute("SELECT * FROM wards WHERE id = ?", (ward_id,)).fetchone()
    if not ward:
        return jsonify(error="Invalid ward_id"), 400

    cur = db.cursor()
    cur.execute(
        "INSERT INTO users (name, contact, password_hash, role) VALUES (?, ?, ?, 'HOUSEHOLD')",
        (name, contact, hash_password(password)),
    )
    user_id = cur.lastrowid
    next_num = db.execute(
        "SELECT COALESCE(MAX(CAST(SUBSTR(household_code, 3) AS INTEGER)), 10000) + 1 AS n FROM households"
    ).fetchone()["n"]
    code = f"H-{next_num}"
    cur.execute(
        "INSERT INTO households (household_code, address, ward_id, district, qr_code, user_id) "
        "VALUES (?, ?, ?, 'Raipur', ?, ?)",
        (code, address, ward_id, f"WASTESEG:{code}", user_id),
    )
    db.execute("UPDATE wards SET total_households = total_households + 1 WHERE id = ?", (ward_id,))
    db.commit()
    return jsonify(success=True, household_code=code, default_password=password), 201


@app.get("/api/admin/collectors")
@require_role("ADMIN")
def admin_list_collectors():
    db = dbmod.get_db()
    rows = db.execute(
        "SELECT c.*, w.ward_name FROM collectors c LEFT JOIN wards w ON w.id = c.ward_id "
        "ORDER BY c.collector_code"
    ).fetchall()
    return jsonify(collectors=dbmod.rows_to_list(rows))


@app.post("/api/admin/collectors")
@require_role("ADMIN")
def admin_add_collector():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    phone = (data.get("phone") or "").strip()
    contact = (data.get("contact") or phone).strip()
    password = data.get("password") or "collect123"
    ward_id = data.get("ward_id")

    if not name or not contact or not ward_id:
        return jsonify(error="name, contact and ward_id are required"), 400

    db = dbmod.get_db()
    if db.execute("SELECT 1 FROM users WHERE contact = ?", (contact,)).fetchone():
        return jsonify(error="An account with this contact already exists"), 409

    cur = db.cursor()
    cur.execute(
        "INSERT INTO users (name, contact, password_hash, role) VALUES (?, ?, ?, 'COLLECTOR')",
        (name, contact, hash_password(password)),
    )
    user_id = cur.lastrowid
    next_num = db.execute(
        "SELECT COALESCE(MAX(CAST(SUBSTR(collector_code, 3) AS INTEGER)), 0) + 1 AS n FROM collectors"
    ).fetchone()["n"]
    code = f"C-{next_num:03d}"
    cur.execute(
        "INSERT INTO collectors (collector_code, name, phone, ward_id, user_id) VALUES (?, ?, ?, ?, ?)",
        (code, name, phone, ward_id, user_id),
    )
    db.commit()
    return jsonify(success=True, collector_code=code, default_password=password), 201


@app.get("/api/admin/collections")
@require_role("ADMIN")
def admin_list_collections():
    db = dbmod.get_db()
    limit = min(int(request.args.get("limit", 100)), 500)
    rows = db.execute(
        "SELECT c.collection_date, c.rating, c.credits_awarded, c.timestamp, "
        "h.household_code, w.ward_name, col.collector_code, col.name AS collector_name "
        "FROM collections c "
        "JOIN households h ON h.id = c.household_id "
        "LEFT JOIN wards w ON w.id = h.ward_id "
        "JOIN collectors col ON col.id = c.collector_id "
        "ORDER BY c.timestamp DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return jsonify(collections=dbmod.rows_to_list(rows))


@app.get("/api/admin/credit-rules")
@require_role("ADMIN")
def admin_get_credit_rules():
    db = dbmod.get_db()
    return jsonify(rules=credit_rules_map(db))


@app.put("/api/admin/credit-rules")
@require_role("ADMIN")
def admin_update_credit_rules():
    data = request.get_json(silent=True) or {}
    db = dbmod.get_db()
    updated = {}
    for rating in config.RATINGS:
        if rating in data:
            try:
                credits = int(data[rating])
            except (TypeError, ValueError):
                return jsonify(error=f"credits for {rating} must be an integer"), 400
            if credits < 0:
                return jsonify(error="credits cannot be negative"), 400
            db.execute("UPDATE credit_rules SET credits = ? WHERE rating = ?", (credits, rating))
            updated[rating] = credits
    db.commit()
    return jsonify(success=True, rules=credit_rules_map(db))


@app.get("/api/admin/rewards")
@require_role("ADMIN")
def admin_list_rewards():
    db = dbmod.get_db()
    rows = db.execute("SELECT * FROM rewards ORDER BY credits_required").fetchall()
    return jsonify(rewards=dbmod.rows_to_list(rows))


@app.post("/api/admin/rewards")
@require_role("ADMIN")
def admin_add_reward():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    description = (data.get("description") or "").strip()
    credits_required = data.get("credits_required")
    if not name or not credits_required:
        return jsonify(error="name and credits_required are required"), 400
    db = dbmod.get_db()
    cur = db.cursor()
    cur.execute(
        "INSERT INTO rewards (name, description, credits_required, available) VALUES (?, ?, ?, 1)",
        (name, description, int(credits_required)),
    )
    db.commit()
    return jsonify(success=True, reward_id=cur.lastrowid), 201


@app.put("/api/admin/rewards/<int:reward_id>")
@require_role("ADMIN")
def admin_update_reward(reward_id):
    data = request.get_json(silent=True) or {}
    db = dbmod.get_db()
    reward = db.execute("SELECT * FROM rewards WHERE id = ?", (reward_id,)).fetchone()
    if not reward:
        return jsonify(error="Reward not found"), 404
    name = data.get("name", reward["name"])
    description = data.get("description", reward["description"])
    credits_required = data.get("credits_required", reward["credits_required"])
    available = int(bool(data.get("available", reward["available"])))
    db.execute(
        "UPDATE rewards SET name=?, description=?, credits_required=?, available=? WHERE id=?",
        (name, description, credits_required, available, reward_id),
    )
    db.commit()
    return jsonify(success=True)


@app.get("/api/admin/redemptions")
@require_role("ADMIN")
def admin_list_redemptions():
    db = dbmod.get_db()
    rows = db.execute(
        "SELECT r.redemption_date, r.credits_used, r.status, h.household_code, rw.name AS reward_name "
        "FROM redemptions r JOIN households h ON h.id = r.household_id "
        "JOIN rewards rw ON rw.id = r.reward_id ORDER BY r.redemption_date DESC LIMIT 100"
    ).fetchall()
    return jsonify(redemptions=dbmod.rows_to_list(rows))


# ===========================================================================
# Frontend static serving (SPA-less multi-page app, no build step required)
# ===========================================================================
@app.route("/")
def serve_index():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/<path:path>")
def serve_static(path):
    full = os.path.join(FRONTEND_DIR, path)
    if os.path.isfile(full):
        return send_from_directory(FRONTEND_DIR, path)
    # Fallback for page routes typed without .html
    if os.path.isfile(full + ".html"):
        return send_from_directory(FRONTEND_DIR, path + ".html")
    return jsonify(error="Not found"), 404


@app.errorhandler(404)
def not_found(e):
    if request.path.startswith("/api/"):
        return jsonify(error="Not found"), 404
    return send_from_directory(FRONTEND_DIR, "index.html")


bootstrap()

# ===========================================================================
# AI PHOTO HINT (optional) - suggests Wet/Dry from a photo, collector still
# makes the final Good/Average/Poor call manually.
# ===========================================================================
@app.post("/api/collector/classify-photo")
@require_role("COLLECTOR", "ADMIN")
def classify_photo():
    if "photo" not in request.files:
        return jsonify(error="No photo file uploaded (expected field name 'photo')"), 400
    photo = request.files["photo"]
    if photo.filename == "":
        return jsonify(error="No photo selected"), 400

    from ml.classify import classify_image, ModelNotAvailable
    try:
        result = classify_image(photo.stream)
    except ModelNotAvailable as e:
        return jsonify(error=str(e)), 503
    except ValueError as e:
        return jsonify(error=str(e)), 400

    return jsonify(
        predicted_class=result["predicted_class"],
        confidence=result["confidence"],
        note="AI suggestion only - the collector's manual rating is authoritative.",
    )

if __name__ == "__main__":
    print(f"[Waste Segregation] Serving on http://localhost:{config.PORT}")
    app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG)
