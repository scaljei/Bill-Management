CREATE TABLE IF NOT EXISTS bills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    statement_date TEXT,
    account_number TEXT,
    amount_due REAL,
    due_date TEXT,
    paid TEXT DEFAULT 'N' CHECK(paid IN ('Y','N')),
    in_collections TEXT DEFAULT 'N' CHECK(in_collections IN ('Y','N')),
    category TEXT,
    notes TEXT,
    pdf_data BLOB,
    pdf_filename TEXT,
    pdf_size INTEGER,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS bill_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_id INTEGER NOT NULL,
    linked_bill_id INTEGER NOT NULL,
    link_type TEXT DEFAULT 'related',
    note TEXT,
    FOREIGN KEY (bill_id) REFERENCES bills(id) ON DELETE CASCADE,
    FOREIGN KEY (linked_bill_id) REFERENCES bills(id) ON DELETE CASCADE,
    UNIQUE(bill_id, linked_bill_id)
);
