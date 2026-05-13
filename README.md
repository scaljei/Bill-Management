# BillVault — PDF Bill Tracking Application

Track, store, and manage bills with PDF storage, OCR field detection, audit logs, and record linking.

---

## Requirements

### Python (3.10+)
Install all Python dependencies with:
```bash
pip install -r requirements.txt
```

| Package | Min Version | Purpose |
|---------|-------------|---------|
| `flask` | 3.0.0 | Web framework |
| `pypdf` | 4.0.0 | Text extraction from digital PDFs |
| `pdf2image` | 1.16.0 | Render scanned PDF pages to images |
| `pytesseract` | 0.3.10 | OCR wrapper for Tesseract |

### System (required for OCR on scanned PDFs)

**macOS**
```bash
brew install tesseract poppler
```

**Ubuntu / Debian**
```bash
sudo apt install tesseract-ocr poppler-utils
```

**Fedora / RHEL**
```bash
sudo dnf install tesseract poppler-utils
```

**Windows**
1. Tesseract: download installer from https://github.com/UB-Mannheim/tesseract/wiki — add to PATH
2. Poppler: download from https://github.com/oschwartz10612/poppler-windows/releases — add `bin/` to PATH

> **Note:** Tesseract and Poppler are only needed for scanned/image PDFs. Digital PDFs (most modern bills) work without them.

---

## Setup & Run

```bash
# 1. Clone
git clone https://github.com/scaljei/Bill-Management.git
cd Bill-Management

# 2. Install Python packages
pip install -r requirements.txt

# 3. Install system deps (see above for your OS)

# 4. Run — dependency check runs automatically on launch
python app.py
```

Open **http://localhost:5000** in your browser.

### Startup options

```bash
python app.py                    # Normal start with interactive dep check
python app.py --auto-install     # Auto-install missing packages without prompting
python app.py --skip-dep-check   # Skip the check entirely
python app.py --port 8080        # Run on a different port
python app.py --host 0.0.0.0     # Expose on all interfaces (LAN access)
```

### Dependency check output

On every launch BillVault checks all Python packages and system binaries:

```
──────────────────────────────────────────────────────
  BillVault — Dependency Check
──────────────────────────────────────────────────────
  ✔ Python 3.12.3

  Python packages
    ✔ flask v3.1.3
    ✔ pypdf v5.9.0
    ✔ pdf2image v1.17.0
    ✔ pytesseract v0.3.13

  System binaries
    ✔ Tesseract OCR  tesseract 5.3.4
    ✔ Poppler (pdftoppm)  pdftoppm version 24.02.0

  All dependencies satisfied.
──────────────────────────────────────────────────────
```

If anything is missing, you'll be prompted:
```
  Missing/outdated Python packages: pypdf>=4.0.0

  Options:
    [A] Auto-install now
    [S] Skip and continue anyway
    [Q] Quit

  Choice [A/s/q]:
```

---

## Features

- **PDF storage** — PDFs stored as BLOBs in SQLite (no external file system)
- **OCR auto-detection** — uploads scan for Provider, Account #, Amount, Due Date, Statement Date, Category
- **Bulk upload** — drag a folder of PDFs; each file scanned in background
- **Activity log** — timestamped audit trail per bill (replaces static notes)
- **Record linking** — link related bills (continuation, dispute, payment plan)
- **Overdue detection** — unpaid bills past due date flagged automatically
- **Collections tracking** — in-collections amounts excluded from "total owed"
- **Categories** — tag bills with sidebar quick-filter

---

## Database Schema

### `bills`
| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| provider | TEXT | Biller name |
| statement_date | TEXT | Date on statement |
| account_number | TEXT | Account identifier |
| amount_due | REAL | Dollar amount |
| due_date | TEXT | Payment due date |
| paid | TEXT (Y/N) | Payment status |
| in_collections | TEXT (Y/N) | Collections status |
| category | TEXT | Bill category |
| notes | TEXT | Legacy (migrated to bill_updates) |
| pdf_data | BLOB | Raw PDF binary |
| pdf_filename | TEXT | Original filename |
| pdf_size | INTEGER | File size in bytes |
| created_at | TEXT | Auto timestamp |
| updated_at | TEXT | Auto timestamp |

### `bill_updates` (audit log)
| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| bill_id | INTEGER FK | → bills.id |
| note | TEXT | Action recorded |
| author | TEXT | Who logged it |
| created_at | TEXT | Auto timestamp |

### `bill_links`
| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| bill_id | INTEGER FK | Source bill |
| linked_bill_id | INTEGER FK | Target bill |
| link_type | TEXT | related / continuation / dispute / payment-plan |
| note | TEXT | Optional note |

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/bills` | List bills (`?search=`, `?paid=`, `?collections=`, `?category=`) |
| POST | `/api/bills` | Create bill (multipart/form-data + optional PDF) |
| GET | `/api/bills/:id` | Bill detail with links and audit log |
| PUT | `/api/bills/:id` | Update bill |
| DELETE | `/api/bills/:id` | Delete bill |
| GET | `/api/bills/:id/pdf` | Stream stored PDF |
| POST | `/api/bills/:id/scan` | Re-run OCR on stored PDF |
| POST | `/api/scan` | OCR an uploaded PDF (returns detected fields, no save) |
| POST | `/api/bills/:id/updates` | Add audit log entry |
| DELETE | `/api/updates/:id` | Delete audit entry |
| POST | `/api/bills/:id/links` | Link two bills |
| DELETE | `/api/links/:id` | Remove a link |
| GET | `/api/stats` | Dashboard statistics |
| GET | `/api/categories` | List all categories |
