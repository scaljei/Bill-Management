# BillVault — PDF Bill Tracking Application

A full-featured bill management application that stores PDF statements in SQLite and provides a modern web UI for tracking, categorizing, and linking bills.

## Features

- **Store PDFs in SQLite** — Binary PDF data stored directly in the database
- **Full CRUD** — Add, edit, view, and delete bills
- **Key Fields**: Provider, Statement Date, Account #, Amount Due, Due Date, Paid (Y/N), In Collections (Y/N)
- **Categories** — Tag bills with sidebar quick-filter
- **Record Linking** — Link related bills (continuations, disputes, payment plans)
- **Overdue Detection** — Unpaid bills past due date are automatically flagged
- **PDF Viewer** — View statements inline in the detail panel
- **Search & Filter** — Real-time search by provider, account number, or notes
- **Dashboard Stats** — Totals: unpaid, overdue, collections, total owed

## Setup

```bash
pip install flask pypdf
python app.py
# Open http://localhost:5000
```

## Original README
First attempt at AI Generated app to manage active bills
