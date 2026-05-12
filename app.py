import sqlite3
import os
from flask import Flask, request, jsonify, send_file, render_template, g
from datetime import datetime
import io

app = Flask(__name__)
DB_PATH = os.path.join(os.path.dirname(__file__), 'bills.db')


def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db:
        db.close()


def init_db():
    with app.app_context():
        db = get_db()
        with open(os.path.join(os.path.dirname(__file__), 'schema.sql')) as f:
            db.executescript(f.read())
        db.commit()


# ── Routes ───────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


# ── Bills CRUD ────────────────────────────────────────────────────────────────

@app.route('/api/bills', methods=['GET'])
def list_bills():
    db = get_db()
    search = request.args.get('search', '')
    paid = request.args.get('paid', '')
    collections = request.args.get('collections', '')
    category = request.args.get('category', '')

    query = """
        SELECT id, provider, statement_date, account_number, amount_due,
               due_date, paid, in_collections, category, notes,
               pdf_filename, pdf_size, created_at, updated_at
        FROM bills WHERE 1=1
    """
    params = []
    if search:
        query += " AND (provider LIKE ? OR account_number LIKE ? OR notes LIKE ?)"
        params += [f'%{search}%'] * 3
    if paid in ('Y', 'N'):
        query += " AND paid = ?"
        params.append(paid)
    if collections in ('Y', 'N'):
        query += " AND in_collections = ?"
        params.append(collections)
    if category:
        query += " AND category = ?"
        params.append(category)
    query += " ORDER BY due_date ASC, created_at DESC"

    rows = db.execute(query, params).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route('/api/bills', methods=['POST'])
def create_bill():
    db = get_db()
    pdf_data = pdf_filename = pdf_size = None

    if 'pdf' in request.files:
        f = request.files['pdf']
        if f.filename:
            pdf_data = f.read()
            pdf_filename = f.filename
            pdf_size = len(pdf_data)

    form = request.form
    try:
        amount = float(form.get('amount_due') or 0) if form.get('amount_due') else None
    except ValueError:
        amount = None

    cur = db.execute("""
        INSERT INTO bills
          (provider, statement_date, account_number, amount_due,
           due_date, paid, in_collections, category, notes,
           pdf_data, pdf_filename, pdf_size)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        form.get('provider', ''),
        form.get('statement_date') or None,
        form.get('account_number', ''),
        amount,
        form.get('due_date') or None,
        form.get('paid', 'N'),
        form.get('in_collections', 'N'),
        form.get('category', ''),
        form.get('notes', ''),
        pdf_data, pdf_filename, pdf_size
    ))
    db.commit()
    return jsonify({'id': cur.lastrowid, 'message': 'Bill created'}), 201


@app.route('/api/bills/<int:bill_id>', methods=['GET'])
def get_bill(bill_id):
    db = get_db()
    row = db.execute("""
        SELECT id, provider, statement_date, account_number, amount_due,
               due_date, paid, in_collections, category, notes,
               pdf_filename, pdf_size, created_at, updated_at
        FROM bills WHERE id=?
    """, (bill_id,)).fetchone()
    if not row:
        return jsonify({'error': 'Not found'}), 404
    bill = dict(row)

    # linked bills
    links = db.execute("""
        SELECT bl.id as link_id, bl.linked_bill_id, bl.link_type, bl.note,
               b.provider, b.due_date, b.amount_due, b.paid
        FROM bill_links bl
        JOIN bills b ON b.id = bl.linked_bill_id
        WHERE bl.bill_id = ?
    """, (bill_id,)).fetchall()
    bill['links'] = [dict(l) for l in links]
    return jsonify(bill)


@app.route('/api/bills/<int:bill_id>', methods=['PUT'])
def update_bill(bill_id):
    db = get_db()
    pdf_data = pdf_filename = pdf_size = None
    has_pdf = False

    if 'pdf' in request.files:
        f = request.files['pdf']
        if f.filename:
            pdf_data = f.read()
            pdf_filename = f.filename
            pdf_size = len(pdf_data)
            has_pdf = True

    form = request.form
    try:
        amount = float(form.get('amount_due') or 0) if form.get('amount_due') else None
    except ValueError:
        amount = None

    if has_pdf:
        db.execute("""
            UPDATE bills SET
              provider=?, statement_date=?, account_number=?, amount_due=?,
              due_date=?, paid=?, in_collections=?, category=?, notes=?,
              pdf_data=?, pdf_filename=?, pdf_size=?,
              updated_at=datetime('now')
            WHERE id=?
        """, (
            form.get('provider', ''), form.get('statement_date') or None,
            form.get('account_number', ''), amount,
            form.get('due_date') or None, form.get('paid', 'N'),
            form.get('in_collections', 'N'), form.get('category', ''),
            form.get('notes', ''), pdf_data, pdf_filename, pdf_size, bill_id
        ))
    else:
        db.execute("""
            UPDATE bills SET
              provider=?, statement_date=?, account_number=?, amount_due=?,
              due_date=?, paid=?, in_collections=?, category=?, notes=?,
              updated_at=datetime('now')
            WHERE id=?
        """, (
            form.get('provider', ''), form.get('statement_date') or None,
            form.get('account_number', ''), amount,
            form.get('due_date') or None, form.get('paid', 'N'),
            form.get('in_collections', 'N'), form.get('category', ''),
            form.get('notes', ''), bill_id
        ))
    db.commit()
    return jsonify({'message': 'Updated'})


@app.route('/api/bills/<int:bill_id>', methods=['DELETE'])
def delete_bill(bill_id):
    db = get_db()
    db.execute("DELETE FROM bills WHERE id=?", (bill_id,))
    db.commit()
    return jsonify({'message': 'Deleted'})


@app.route('/api/bills/<int:bill_id>/pdf')
def get_pdf(bill_id):
    db = get_db()
    row = db.execute("SELECT pdf_data, pdf_filename FROM bills WHERE id=?", (bill_id,)).fetchone()
    if not row or not row['pdf_data']:
        return jsonify({'error': 'No PDF'}), 404
    return send_file(
        io.BytesIO(row['pdf_data']),
        mimetype='application/pdf',
        download_name=row['pdf_filename'] or f'bill_{bill_id}.pdf',
        as_attachment=False
    )


# ── Links ─────────────────────────────────────────────────────────────────────

@app.route('/api/bills/<int:bill_id>/links', methods=['POST'])
def add_link(bill_id):
    db = get_db()
    data = request.get_json()
    linked_id = data.get('linked_bill_id')
    link_type = data.get('link_type', 'related')
    note = data.get('note', '')

    if linked_id == bill_id:
        return jsonify({'error': 'Cannot link to self'}), 400

    try:
        db.execute(
            "INSERT INTO bill_links (bill_id, linked_bill_id, link_type, note) VALUES (?,?,?,?)",
            (bill_id, linked_id, link_type, note)
        )
        # mirror link
        db.execute(
            "INSERT OR IGNORE INTO bill_links (bill_id, linked_bill_id, link_type, note) VALUES (?,?,?,?)",
            (linked_id, bill_id, link_type, note)
        )
        db.commit()
    except sqlite3.IntegrityError:
        return jsonify({'error': 'Already linked'}), 409

    return jsonify({'message': 'Linked'}), 201


@app.route('/api/links/<int:link_id>', methods=['DELETE'])
def delete_link(link_id):
    db = get_db()
    db.execute("DELETE FROM bill_links WHERE id=?", (link_id,))
    db.commit()
    return jsonify({'message': 'Link removed'})


# ── Stats ─────────────────────────────────────────────────────────────────────

@app.route('/api/stats')
def stats():
    db = get_db()
    row = db.execute("""
        SELECT
          COUNT(*) as total,
          SUM(CASE WHEN paid='N' THEN 1 ELSE 0 END) as unpaid,
          SUM(CASE WHEN in_collections='Y' THEN 1 ELSE 0 END) as in_collections,
          SUM(CASE WHEN paid='N' THEN COALESCE(amount_due,0) ELSE 0 END) as total_owed,
          SUM(COALESCE(amount_due,0)) as total_amount
        FROM bills
    """).fetchone()
    overdue = db.execute("""
        SELECT COUNT(*) as cnt FROM bills
        WHERE paid='N' AND due_date < date('now') AND due_date IS NOT NULL
    """).fetchone()
    categories = db.execute("""
        SELECT category, COUNT(*) as cnt FROM bills
        WHERE category != '' AND category IS NOT NULL
        GROUP BY category ORDER BY cnt DESC
    """).fetchall()
    return jsonify({
        **dict(row),
        'overdue': overdue['cnt'],
        'categories': [dict(c) for c in categories]
    })


@app.route('/api/categories')
def categories():
    db = get_db()
    rows = db.execute("""
        SELECT DISTINCT category FROM bills
        WHERE category != '' AND category IS NOT NULL ORDER BY category
    """).fetchall()
    return jsonify([r['category'] for r in rows])


if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000)
