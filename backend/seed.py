"""
Seed/demo data generator for Waste Segregation.

Populates the database with a realistic Raipur (Chhattisgarh) two-ward
pilot: wards, collectors, ~35 households, ~2 weeks of collection history,
green-credit transactions and a handful of rewards -- so the app is fully
demoable immediately after installation, with zero manual data entry.

Run directly:  python seed.py
Or import run_seed(conn) from app.py on first launch.
"""
import random
import sqlite3
from datetime import date, timedelta

import config
from auth import hash_password

random.seed(42)  # reproducible demo data

WARDS = [
    ("Ward 12 - Shankar Nagar", "Raipur"),
    ("Ward 15 - Telibandha", "Raipur"),
    ("Ward 8 - Amanaka", "Raipur"),
    ("Ward 21 - Devendra Nagar", "Raipur"),
]

STREET_NAMES = [
    "Ashoka Nagar Road", "Pandri Main Road", "Civil Lines", "Gudhiyari Road",
    "Shankar Nagar Main Road", "Telibandha Lake Road", "Amanaka Chowk",
    "Devendra Nagar Extension", "Fafadih Road", "Mowa Link Road",
    "Kalibadi Marg", "Jail Road", "Station Road", "GE Road",
]

FIRST_NAMES = [
    "Anil", "Sunita", "Rajesh", "Priya", "Manoj", "Kavita", "Suresh",
    "Deepa", "Vikram", "Neha", "Ramesh", "Pooja", "Ashok", "Meena",
    "Sanjay", "Rekha", "Dinesh", "Shweta", "Naveen", "Anita", "Praveen",
    "Sarita", "Ravi", "Geeta", "Ajay", "Kiran", "Vinod", "Usha",
    "Arun", "Nisha",
]
LAST_NAMES = [
    "Sharma", "Verma", "Sahu", "Patel", "Sinha", "Yadav", "Chandrakar",
    "Dewangan", "Agrawal", "Tiwari", "Mishra", "Nayak", "Rathore", "Jain",
]

RATING_WEIGHTS = {"GOOD": 0.55, "AVERAGE": 0.32, "POOR": 0.13}


def _rand_name():
    return f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"


def _weighted_rating():
    r = random.random()
    if r < RATING_WEIGHTS["GOOD"]:
        return "GOOD"
    if r < RATING_WEIGHTS["GOOD"] + RATING_WEIGHTS["AVERAGE"]:
        return "AVERAGE"
    return "POOR"


def run_seed(conn: sqlite3.Connection):
    cur = conn.cursor()

    # Wipe existing data (idempotent reseed) -------------------------------
    for table in (
        "redemptions", "green_credit_transactions", "collections",
        "rewards", "collectors", "households", "wards", "users",
        "credit_rules",
    ):
        cur.execute(f"DELETE FROM {table}")

    # Credit rules -----------------------------------------------------------
    for rating, credits in config.DEFAULT_CREDIT_RULES.items():
        cur.execute(
            "INSERT INTO credit_rules (rating, credits) VALUES (?, ?)",
            (rating, credits),
        )

    # Wards --------------------------------------------------------------
    ward_ids = []
    for ward_name, city in WARDS:
        cur.execute(
            "INSERT INTO wards (ward_name, city, total_households) VALUES (?, ?, 0)",
            (ward_name, city),
        )
        ward_ids.append(cur.lastrowid)

    # --- Admin user -------------------------------------------------------
    cur.execute(
        "INSERT INTO users (name, contact, password_hash, role) VALUES (?, ?, ?, ?)",
        ("Raipur ULB Admin", "admin@wastesegregation.in", hash_password("admin123"), "ADMIN"),
    )

    # --- Collectors (3-5, one per ward, first two share duty on ward 1) ---
    collector_defs = [
        ("C-001", "Ramesh Kumar", "9876500011", ward_ids[0], "collector1@wastesegregation.in", "collect123"),
        ("C-002", "Sunil Patel", "9876500012", ward_ids[1], "collector2@wastesegregation.in", "collect123"),
        ("C-003", "Manoj Sahu", "9876500013", ward_ids[2], "collector3@wastesegregation.in", "collect123"),
        ("C-004", "Deepak Verma", "9876500014", ward_ids[3], "collector4@wastesegregation.in", "collect123"),
    ]
    collector_ids = {}
    for code, name, phone, ward_id, contact, pwd in collector_defs:
        cur.execute(
            "INSERT INTO users (name, contact, password_hash, role) VALUES (?, ?, ?, 'COLLECTOR')",
            (name, contact, hash_password(pwd)),
        )
        user_id = cur.lastrowid
        cur.execute(
            "INSERT INTO collectors (collector_code, name, phone, ward_id, user_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (code, name, phone, ward_id, user_id),
        )
        collector_ids[code] = cur.lastrowid

    # --- Households (35 total, spread across wards) -----------------------
    # H-10001 is reserved as the "hero" demo household with a well-known
    # login, used for the live scan-and-rate demo. It intentionally has NO
    # collection recorded for today, so the collector demo can rate it live.
    household_ids = []
    household_ward_map = {}
    next_code_num = 10001
    TOTAL_HOUSEHOLDS = 35

    for i in range(TOTAL_HOUSEHOLDS):
        code = f"H-{next_code_num}"
        next_code_num += 1
        ward_id = ward_ids[i % len(ward_ids)]
        street = random.choice(STREET_NAMES)
        house_no = random.randint(1, 250)
        address = f"House No. {house_no}, {street}"

        if code == "H-10001":
            name, contact, pwd = "Demo Household (Sharma Residence)", "demo.household@wastesegregation.in", "house123"
        else:
            name = _rand_name()
            contact = f"9876{600000 + i}"
            pwd = "house123"

        cur.execute(
            "INSERT INTO users (name, contact, password_hash, role) VALUES (?, ?, ?, 'HOUSEHOLD')",
            (name, contact, hash_password(pwd)),
        )
        user_id = cur.lastrowid

        qr_payload = f"WASTESEG:{code}"
        cur.execute(
            "INSERT INTO households (household_code, address, ward_id, district, qr_code, user_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (code, address, ward_id, "Raipur", qr_payload, user_id),
        )
        hh_id = cur.lastrowid
        household_ids.append(hh_id)
        household_ward_map[hh_id] = ward_id

    # keep ward household counts accurate
    for ward_id in ward_ids:
        count = sum(1 for w in household_ward_map.values() if w == ward_id)
        cur.execute("UPDATE wards SET total_households = ? WHERE id = ?", (count, ward_id))

    # map ward -> a collector working that ward (for realistic assignment)
    ward_to_collector_code = {
        ward_ids[0]: "C-001",
        ward_ids[1]: "C-002",
        ward_ids[2]: "C-003",
        ward_ids[3]: "C-004",
    }

    # --- Collection history (last 14 days, NOT including today) -----------
    rules = {r["rating"]: r["credits"] for r in cur.execute("SELECT rating, credits FROM credit_rules")}
    today = date.today()
    HISTORY_DAYS = 14

    for hh_id in household_ids:
        ward_id = household_ward_map[hh_id]
        collector_id = collector_ids[ward_to_collector_code[ward_id]]

        if hh_id == household_ids[0]:  # H-10001, keep today un-rated for the live demo
            day_range = range(1, HISTORY_DAYS + 1)
        else:
            day_range = range(0, HISTORY_DAYS)  # some data through "today" for realism

        # simulate a slightly-improving trend + occasional missed pickup
        for offset in day_range:
            if random.random() < 0.06:  # ~6% missed collection day
                continue
            collection_date = (today - timedelta(days=offset)).isoformat()
            rating = _weighted_rating()
            credits = rules[rating]

            try:
                cur.execute(
                    "INSERT INTO collections "
                    "(household_id, collector_id, rating, credits_awarded, collection_date) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (hh_id, collector_id, rating, credits, collection_date),
                )
            except sqlite3.IntegrityError:
                continue
            collection_id = cur.lastrowid

            if credits > 0:
                cur.execute(
                    "INSERT INTO green_credit_transactions "
                    "(household_id, collection_id, amount, transaction_type, description) "
                    "VALUES (?, ?, ?, 'EARNED', ?)",
                    (hh_id, collection_id, credits, f"Collection rated {rating.title()} on {collection_date}"),
                )

    # --- Rewards catalogue --------------------------------------------------
    rewards = [
        ("Rs.50 Electricity Bill Credit", "Mock redemption against your next electricity bill (prototype only).", 100),
        ("Rs.50 Property Tax Credit", "Mock redemption against annual property tax (prototype only).", 120),
        ("Kirana Store Voucher - Rs.100", "Redeemable at partnered local kirana stores (mock partner).", 150),
        ("Reusable Cloth Bag Set", "A set of 3 reusable segregation bags delivered by your collector.", 40),
        ("Compost Kit (Home Composting Starter)", "Starter kit to compost your wet waste at home.", 200),
        ("Waste Segregation Champion Certificate", "Digital recognition certificate for consistent Good ratings.", 60),
    ]
    for name, desc, cr in rewards:
        cur.execute(
            "INSERT INTO rewards (name, description, credits_required, available) VALUES (?, ?, ?, 1)",
            (name, desc, cr),
        )

    conn.commit()
    print(f"Seeded: {len(WARDS)} wards, {len(collector_defs)} collectors, "
          f"{TOTAL_HOUSEHOLDS} households, credit rules, rewards, "
          f"~{HISTORY_DAYS} days of collection history.")


if __name__ == "__main__":
    conn = sqlite3.connect(config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    import db as dbmod
    conn.executescript(dbmod.SCHEMA)
    run_seed(conn)
    conn.close()
