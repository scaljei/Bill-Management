"""
ocr.py — PDF text extraction + bill field parser for BillVault.

Strategy:
  1. Try pypdf for embedded text (fast, accurate for digital PDFs).
  2. If little/no text found, fall back to pdf2image + pytesseract (scanned PDFs).
  3. Run regex heuristics over extracted text to identify bill fields.
  4. Return a dict of suggested values + confidence flags.
"""

import re
import io
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── Text extraction ───────────────────────────────────────────────────────────

def extract_text_pypdf(pdf_bytes: bytes) -> str:
    try:
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        parts = []
        for page in reader.pages[:4]:          # limit to first 4 pages
            try:
                parts.append(page.extract_text() or '')
            except Exception:
                pass
        return '\n'.join(parts)
    except Exception as e:
        logger.warning('pypdf extraction failed: %s', e)
        return ''


def extract_text_ocr(pdf_bytes: bytes) -> str:
    try:
        from pdf2image import convert_from_bytes
        import pytesseract
        images = convert_from_bytes(pdf_bytes, first_page=1, last_page=3, dpi=200)
        parts = []
        for img in images:
            text = pytesseract.image_to_string(img, config='--psm 6')
            parts.append(text)
        return '\n'.join(parts)
    except Exception as e:
        logger.warning('OCR extraction failed: %s', e)
        return ''


def get_text(pdf_bytes: bytes) -> tuple[str, str]:
    """Return (text, method) where method is 'digital' or 'ocr'."""
    text = extract_text_pypdf(pdf_bytes)
    # If we got meaningful text (>100 non-whitespace chars), use it
    if len(text.replace(' ', '').replace('\n', '')) > 100:
        return text, 'digital'
    # Fall back to OCR
    text = extract_text_ocr(pdf_bytes)
    return text, 'ocr'


# ── Field parsers ─────────────────────────────────────────────────────────────

def _find_amount(text: str) -> Optional[str]:
    """Find the most likely 'amount due' dollar value."""
    # Priority labels first
    priority = [
        r'(?:amount\s+due|total\s+due|balance\s+due|payment\s+due|'
        r'minimum\s+(?:payment|due)|total\s+amount\s+due|please\s+pay)'
        r'[:\s\-]*\$?([\d,]+\.\d{2})',
    ]
    for pattern in priority:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(1).replace(',', '')

    # Fallback: largest dollar amount on a line containing "due", "total", "pay"
    candidates = re.findall(
        r'(?:due|total|pay|owe|balance)[^\n$]*\$?\s*([\d,]+\.\d{2})',
        text, re.IGNORECASE
    )
    if candidates:
        try:
            return str(max(float(v.replace(',', '')) for v in candidates))
        except ValueError:
            pass

    # Last resort: largest standalone dollar amount in document
    all_amounts = re.findall(r'\$\s*([\d,]+\.\d{2})', text)
    if all_amounts:
        try:
            return str(max(float(v.replace(',', '')) for v in all_amounts))
        except ValueError:
            pass
    return None


def _parse_date(raw: str) -> Optional[str]:
    """Normalise a raw date string to YYYY-MM-DD."""
    raw = raw.strip().rstrip('.')
    # MM/DD/YYYY or M/D/YY
    m = re.match(r'(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})$', raw)
    if m:
        mo, dy, yr = m.groups()
        yr = ('20' + yr) if len(yr) == 2 else yr
        try:
            from datetime import date
            d = date(int(yr), int(mo), int(dy))
            return d.isoformat()
        except ValueError:
            pass

    # Month name formats: January 15, 2026 / Jan 15 2026 / 15 Jan 2026
    months = {'jan':1,'feb':2,'mar':3,'apr':4,'may':5,'jun':6,
              'jul':7,'aug':8,'sep':9,'oct':10,'nov':11,'dec':12}
    m2 = re.match(
        r'(?:(\d{1,2})\s+)?([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})', raw)
    if m2:
        _, mon, dy, yr = m2.groups()
        mo_num = months.get(mon[:3].lower())
        if mo_num:
            try:
                from datetime import date
                d = date(int(yr), mo_num, int(dy))
                return d.isoformat()
            except ValueError:
                pass
    # YYYY-MM-DD already
    m3 = re.match(r'(\d{4})-(\d{2})-(\d{2})$', raw)
    if m3:
        return raw
    return None


def _find_date(text: str, labels: list[str]) -> Optional[str]:
    """Search for a date following any of the given label keywords."""
    date_pattern = (
        r'(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}'          # 01/15/2026
        r'|[A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4}'      # January 15, 2026
        r'|\d{4}-\d{2}-\d{2})'                          # 2026-01-15
    )
    label_re = '|'.join(re.escape(l) for l in labels)
    pattern = rf'(?:{label_re})\s*[:\-]?\s*{date_pattern}'
    m = re.search(pattern, text, re.IGNORECASE)
    if m:
        return _parse_date(m.group(1))
    return None


def _find_account(text: str) -> Optional[str]:
    patterns = [
        r'(?:account\s*(?:number|no\.?|#)|acct\.?\s*(?:no\.?|#)?)\s*[:\-]?\s*([A-Z0-9\-]{4,20})',
        r'(?:invoice\s*(?:number|no\.?|#))\s*[:\-]?\s*([A-Z0-9\-]{4,20})',
        r'(?:customer\s*(?:id|number|no\.?))\s*[:\-]?\s*([A-Z0-9\-]{4,20})',
        r'(?:policy\s*(?:number|no\.?))\s*[:\-]?\s*([A-Z0-9\-]{4,20})',
        r'(?:member\s*(?:id|number|no\.?))\s*[:\-]?\s*([A-Z0-9\-]{4,20})',
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            val = m.group(1).strip()
            if len(val) >= 4:
                return val
    return None


def _find_provider(text: str, filename: str) -> Optional[str]:
    """Best-effort provider name from text or filename."""
    # Common utility/provider headers near top of document
    lines = [l.strip() for l in text.split('\n')[:20] if l.strip()]

    # Skip very short lines and lines that look like addresses/dates
    candidates = [
        l for l in lines
        if 4 < len(l) < 60
        and not re.match(r'^[\d\s\-/,\.]+$', l)
        and not re.search(r'\d{5}', l)          # zip codes
        and not re.search(r'\d{1,2}/\d{1,2}', l)  # dates
    ]

    # Known provider name patterns
    known = re.search(
        r'\b(AT&T|Verizon|Comcast|Xfinity|T-Mobile|Sprint|Charter|Spectrum|'
        r'Cox|CenturyLink|Lumen|Frontier|Windstream|Consolidated|'
        r'Pacific Gas|PG&E|Con Edison|ConEd|Duke Energy|Dominion|Xcel|'
        r'Eversource|Entergy|Ameren|Evergy|AEP|FirstEnergy|Exelon|'
        r'American Water|Aqua|Veolia|United Water|LADWP|'
        r'Kaiser|Aetna|BlueCross|Blue Cross|Cigna|Humana|UnitedHealth|'
        r'Anthem|CVS|Walgreens|LabCorp|Quest Diagnostics|'
        r'Amazon|Apple|Google|Netflix|Hulu|Spotify|Adobe|Microsoft|'
        r'Chase|Bank of America|Wells Fargo|Citibank|Capital One|Discover)\b',
        text[:500], re.IGNORECASE
    )
    if known:
        return known.group(1)

    # First substantial non-address line near top
    if candidates:
        return candidates[0]

    # Fall back to filename (strip extension and clean up)
    name = re.sub(r'\.pdf$', '', filename, flags=re.IGNORECASE)
    name = re.sub(r'[_\-]', ' ', name).strip()
    if name:
        return name.title()

    return None


def _find_category(provider: Optional[str], text: str) -> Optional[str]:
    """Infer a likely category from provider name or document text."""
    combined = ((provider or '') + ' ' + text[:300]).lower()
    if re.search(r'\b(electric|gas|water|utility|utilities|power|energy|sewer|trash)\b', combined):
        return 'Utilities'
    if re.search(r'\b(hospital|medical|clinic|health|doctor|dental|vision|pharmacy|rx|insurance|'
                 r'lab|radiology|urgent\s*care|physician|surgery)\b', combined):
        return 'Medical'
    if re.search(r'\b(rent|lease|apartment|housing|landlord|property)\b', combined):
        return 'Rent'
    if re.search(r'\b(phone|mobile|wireless|cellular|internet|cable|broadband|tv|streaming)\b', combined):
        return 'Telecom'
    if re.search(r'\b(credit\s*card|loan|mortgage|auto\s*loan|student\s*loan|finance)\b', combined):
        return 'Finance'
    if re.search(r'\b(insurance|auto|homeowner|renters|life\s*insurance)\b', combined):
        return 'Insurance'
    if re.search(r'\b(subscription|software|saas|adobe|microsoft|google|amazon)\b', combined):
        return 'Subscription'
    return None


# ── Main entry point ──────────────────────────────────────────────────────────

def extract_bill_fields(pdf_bytes: bytes, filename: str = '') -> dict:
    """
    Extract bill fields from PDF bytes.
    Returns dict with keys: provider, account_number, amount_due,
    statement_date, due_date, category, _method, _raw_text, _detected_fields
    Values are None if not found.
    """
    result = {
        'provider': None,
        'account_number': None,
        'amount_due': None,
        'statement_date': None,
        'due_date': None,
        'category': None,
        '_method': None,
        '_detected_fields': [],
    }

    try:
        text, method = get_text(pdf_bytes)
        result['_method'] = method

        if not text.strip():
            return result

        # Amount
        amt = _find_amount(text)
        if amt:
            result['amount_due'] = amt
            result['_detected_fields'].append('amount_due')

        # Due date
        due = _find_date(text, [
            'due date', 'payment due', 'pay by', 'payment by',
            'due on', 'must be received by', 'please pay by'
        ])
        if due:
            result['due_date'] = due
            result['_detected_fields'].append('due_date')

        # Statement date
        stmt = _find_date(text, [
            'statement date', 'billing date', 'invoice date',
            'bill date', 'date of service', 'service date',
            'period ending', 'billing period'
        ])
        if stmt:
            result['statement_date'] = stmt
            result['_detected_fields'].append('statement_date')

        # Account number
        acct = _find_account(text)
        if acct:
            result['account_number'] = acct
            result['_detected_fields'].append('account_number')

        # Provider
        provider = _find_provider(text, filename)
        if provider:
            result['provider'] = provider
            result['_detected_fields'].append('provider')

        # Category
        category = _find_category(provider, text)
        if category:
            result['category'] = category
            result['_detected_fields'].append('category')

    except Exception as e:
        logger.error('extract_bill_fields error: %s', e)

    return result
