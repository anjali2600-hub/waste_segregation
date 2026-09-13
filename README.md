# Waste Segregation

**A behaviour-first bridge to waste segregation at the source.**

A low-cost, QR-based digital layer over an existing door-to-door waste
collection system - no IoT bins, no new hardware. A collector scans a
household's QR tag, rates that day's segregation as Good/Average/Poor, and
the system automatically awards Green Credits and feeds a ward-wise
compliance dashboard for the ULB (Urban Local Body).

## Problem

In Tier 2/3 Indian cities, households often mix wet and dry waste even
though source segregation is mandatory. Households get no immediate
feedback or benefit for segregating correctly, and collectors often accept
mixed waste anyway.

## Solution

Every household gets a unique QR tag. The existing collector, using their
own smartphone, scans the tag at the doorstep and rates that day's
segregation. Green Credits are awarded automatically based on the rating,
and every collection feeds a live ward-wise compliance dashboard for the
ULB - turning an invisible daily habit into visible, rewarded, trackable
data.

## Features

**Household**
- Register / log in, unique household ID (e.g. `H-10023`)
- View personal QR code (`WASTESEG:H-10023`)
- Today's collection status, Green Credit balance and transaction history
- Segregation history, 30-day performance summary
- Browse and redeem rewards (prototype/mock redemption)

**Collector**
- Log in, see households on their ward route and today's rating progress
- Scan a household's QR with the device camera, or type the ID manually
  (manual entry always works, even if camera permissions fail)
- Rate the collection Good / Average / Poor in one tap
- **Optional AI photo hint**: snap or upload a photo of the waste and a
  trained image classifier suggests Wet (Organic) or Dry (Recyclable) -
  this is a hint only; the collector always makes the final manual rating
- Automatic Green Credit calculation and confirmation

**ULB / Admin**
- City-wide metrics: households, active households, today's collections,
  segregation rate, total credits issued, collectors
- Ward-wise compliance heatmap and performance table
- Manage households, collectors (with ward assignment), rewards
- Configure Green Credit rules (credits per rating) without touching code
- Daily/weekly segregation trend, top households, top wards
- Full collection and redemption logs

## Architecture

A single Flask process serves both the JSON REST API (`/api/...`) and the
static frontend, so the whole prototype runs with one command and no build
step.


## Tech stack

| Layer          | Technology                                              |
|----------------|----------------------------------------------------------|
| Backend        | Python 3, Flask (REST API + static file serving)         |
| Auth           | PyJWT (stateless JWT), Werkzeug PBKDF2 password hashing  |
| Database       | SQLite (Python's built-in `sqlite3` module)               |
| Frontend       | Plain HTML5 / CSS3 / vanilla JavaScript (no framework)    |
| QR generation  | `qrcodejs` (CDN)                                          |
| QR scanning    | `html5-qrcode` (CDN, uses the device camera)              |
| AI photo hint  | TensorFlow/Keras, MobileNetV2 transfer learning           |

## Database schema

SQLite file: `backend/waste_segregation.db` (created automatically on first run).

| Table                        | Purpose |
|-------------------------------|---------|
| `users`                       | Login identity for all three roles, password hash |
| `households`                  | Household profile, ward, unique QR payload |
| `collectors`                  | Collector profile, assigned ward |
| `collections`                 | One row per household per day: rating + credits awarded |
| `green_credit_transactions`   | Ledger of every credit earned/redeemed - balances are derived from this |
| `rewards`                     | Reward catalogue |
| `redemptions`                 | Redemption records |
| `wards`                       | Ward/city reference data |
| `credit_rules`                | Runtime-configurable Good/Average/Poor -> credits mapping |

## Installation

### Prerequisites
- Python 3.9+
- (Optional, only for the AI photo hint feature) a Kaggle account, to
  download the training dataset

### Windows - exact commands

```bat
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r ..\requirements.txt
python app.py
```

### macOS / Linux

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r ../requirements.txt
python3 app.py
```

The first run automatically creates `waste_segregation.db` and seeds it
with demo data (4 Raipur wards, 4 collectors, 35 households, ~14 days of
collection history, 6 rewards). No manual data entry needed.

Open **http://localhost:5000**.

## Demo accounts

| Role      | Login                              | Password     | Notes |
|-----------|--------------------------------------|--------------|-------|
| Household | `demo.household@wastesegregation.in` | `house123`   | Household **H-10001**, deliberately left un-rated today for a live demo |
| Collector | `collector1@wastesegregation.in`     | `collect123` | Collector **C-001**, assigned to H-10001's ward |
| Admin     | `admin@wastesegregation.in`          | `admin123`   | Raipur ULB Admin - full dashboard access |

## API reference

All endpoints return JSON. Authenticated endpoints require
`Authorization: Bearer <token>`, obtained from `/api/auth/login`.

**Auth**: `/api/auth/login`, `/api/auth/register`, `/api/auth/me`, `/api/wards`

**Household**: `/api/households/:code`, `/api/households/:code/qr`,
`/api/households/:code/history`, `/api/households/:code/credits`,
`/api/households/:code/summary`, `/api/households/:code/redemptions`

**Collector**: `/api/collector/lookup?code=...`, `/api/collector/today`,
`POST /api/collections`, `POST /api/collector/classify-photo` (AI photo hint)

**Rewards**: `/api/rewards`, `POST /api/rewards/redeem`

**Admin**: `/api/admin/dashboard`, `/api/admin/wards`, `/api/admin/analytics`,
`/api/admin/households`, `/api/admin/collectors`, `/api/admin/collections`,
`/api/admin/credit-rules`, `/api/admin/rewards`, `/api/admin/redemptions`

## AI photo hint (optional feature)

The collector's Scan QR tab includes an optional "AI photo check" - upload
or snap a photo of the waste, and a MobileNetV2-based classifier
(trained on Kaggle's "Waste Classification data" dataset, ~25,000 images,
90.7% test accuracy) suggests Wet or Dry with a confidence score. This is
**always a hint, never a decision** - the collector's manual
Good/Average/Poor rating is the only thing that gets recorded.

To retrain the model yourself:
```bash
cd backend
kaggle datasets download -d techsash/waste-classification-data -p ml_data --unzip
python ml/train_model.py
```
This produces `backend/ml/waste_classifier.keras` and `backend/ml/class_map.json`.

## Demo flow

1. Log in as the household - see today's status is "Not rated yet"
2. View the QR code on the "My QR" tab
3. Log in as the collector - scan that QR (or type `H-10001` manually)
4. Optionally test the AI photo hint, then click Good/Average/Poor
5. Credits are awarded instantly; log back in as the household to see the
   updated balance and history
6. Log in as admin - see the new collection reflected in the dashboard,
   ward heatmap, and analytics immediately

## Prototype limitations

- Green Credits are **not** connected to any real government property tax
  or electricity billing system - redemption is mock/prototype only.
- ULB compliance data shown is a demonstration dataset for Raipur,
  Chhattisgarh, not legally recognized by any real municipal body.
- The AI photo hint is a decision-support suggestion only, never an
  automatic rating - the human collector's judgement is authoritative.
- Uses Flask's built-in development server - fine for a local demo, not a
  production deployment.
- Single-SQLite-file architecture - fine for a demo/pilot; a production
  multi-ward rollout would need a proper server-based database.