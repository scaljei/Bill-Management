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

# Minimum meaningful (non-whitespace) chars from pypdf before we trust it
_DIGITAL_MIN_CHARS = 30


# ── Text extraction ───────────────────────────────────────────────────────────

def extract_text_pypdf(pdf_bytes: bytes) -> str:
    try:
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        parts = []
        for page in reader.pages[:4]:
            try:
                t = page.extract_text() or ''
                parts.append(t)
            except Exception as e:
                logger.debug('pypdf page error: %s', e)
        return '\n'.join(parts)
    except Exception as e:
        logger.warning('pypdf extraction failed: %s', e)
        return ''


def extract_text_ocr(pdf_bytes: bytes) -> str:
    try:
        from pdf2image import convert_from_bytes
        import pytesseract
        images = convert_from_bytes(pdf_bytes, first_page=1, last_page=3, dpi=250)
        parts = []
        for img in images:
            text = pytesseract.image_to_string(img, config='--psm 6 --oem 3')
            parts.append(text)
        combined = '\n'.join(parts)
        logger.debug('OCR extracted %d chars', len(combined))
        return combined
    except Exception as e:
        logger.warning('OCR extraction failed: %s', e)
        return ''


def get_text(pdf_bytes: bytes) -> tuple:
    """Return (text, method) where method is 'digital' or 'ocr'."""
    text = extract_text_pypdf(pdf_bytes)
    meaningful = len(re.sub(r'\s', '', text))
    if meaningful >= _DIGITAL_MIN_CHARS:
        logger.debug('Using digital text (%d non-ws chars)', meaningful)
        return text, 'digital'
    logger.debug('pypdf yielded %d non-ws chars — falling back to OCR', meaningful)
    text = extract_text_ocr(pdf_bytes)
    return text, 'ocr'


# ── Normalise OCR noise ───────────────────────────────────────────────────────

def _normalise(text: str) -> str:
    """
    Fix OCR word-splits like 'State ment' -> 'Statement', 'Acco unt' -> 'Account'
    without merging real separate words like 'Statement Date' or 'Amount Due'.
    Uses a targeted word list of terms commonly split by OCR on bill documents.
    """
    known_splits = [
        (r'Acc\s*o\s*unt', 'Account'),
        (r'State\s+ment',  'Statement'),
        (r'Stat\s+ement',  'Statement'),
        (r'Amo\s+unt',     'Amount'),
        (r'Pay\s+ment',    'Payment'),
        (r'Bal\s+ance',    'Balance'),
        (r'Ser\s+vice',    'Service'),
        (r'Cus\s+tomer',   'Customer'),
        (r'In\s+voice',    'Invoice'),
        (r'Bil\s+ling',    'Billing'),
        (r'Mini\s+mum',    'Minimum'),
        (r'Elec\s+tric',   'Electric'),
        (r'Util\s+ity',    'Utility'),
        (r'Insur\s+ance',  'Insurance'),
        (r'Sub\s+scriber', 'Subscriber'),
        (r'Num\s+ber',     'Number'),
        (r'Mem\s+ber',     'Member'),
        (r'Pol\s+icy',     'Policy'),
        (r'Prev\s+ious',   'Previous'),
        (r'Cur\s+rent',    'Current'),
        (r'To\s+tal',      'Total'),
        (r'Provi\s+der',   'Provider'),
        (r'Re\s+ceived',   'Received'),
    ]
    for pattern, replacement in known_splits:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


# ── Field parsers ─────────────────────────────────────────────────────────────

def _find_amount(text: str) -> Optional[str]:
    priority_patterns = [
        r'(?:total\s+amount\s+due|amount\s+due|balance\s+due|total\s+due|'
        r'payment\s+due|please\s+pay|minimum\s+(?:payment\s+)?due|'
        r'new\s+balance|current\s+(?:amount\s+)?due)'
        r'[:\s\-]*\$?\s*([\d,]+\.\d{2})',
    ]
    for pattern in priority_patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(1).replace(',', '')

    candidates = re.findall(
        r'(?:due|total|pay|owe|balance|current)[^\n$]{0,30}\$?\s*([\d,]+\.\d{2})',
        text, re.IGNORECASE
    )
    if candidates:
        try:
            return str(max(float(v.replace(',', '')) for v in candidates))
        except ValueError:
            pass

    all_amounts = re.findall(r'\$\s*([\d,]+\.\d{2})', text)
    if all_amounts:
        try:
            return str(max(float(v.replace(',', '')) for v in all_amounts))
        except ValueError:
            pass
    return None


def _parse_date(raw: str) -> Optional[str]:
    raw = raw.strip().rstrip('.,')
    # MM/DD/YYYY or M/D/YY
    m = re.match(r'^(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})$', raw)
    if m:
        mo, dy, yr = m.groups()
        yr = ('20' + yr) if len(yr) == 2 else yr
        try:
            from datetime import date
            return date(int(yr), int(mo), int(dy)).isoformat()
        except ValueError:
            pass

    months = {
        'jan':1,'feb':2,'mar':3,'apr':4,'may':5,'jun':6,
        'jul':7,'aug':8,'sep':9,'oct':10,'nov':11,'dec':12,
        'january':1,'february':2,'march':3,'april':4,'june':6,
        'july':7,'august':8,'september':9,'october':10,'november':11,'december':12,
    }
    m2 = re.match(r'^([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})$', raw)
    if m2:
        mon, dy, yr = m2.groups()
        mo_num = months.get(mon.lower())
        if mo_num:
            try:
                from datetime import date
                return date(int(yr), mo_num, int(dy)).isoformat()
            except ValueError:
                pass

    m3 = re.match(r'^(\d{4})-(\d{2})-(\d{2})$', raw)
    if m3:
        return raw
    return None


def _find_date(text: str, labels: list) -> Optional[str]:
    date_pat = (
        r'(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}'
        r'|[A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4}'
        r'|\d{4}-\d{2}-\d{2})'
    )
    label_re = '|'.join(re.escape(l) for l in labels)
    pattern = rf'(?:{label_re})\s*[:\-]?\s*{date_pat}'
    m = re.search(pattern, text, re.IGNORECASE)
    if m:
        return _parse_date(m.group(1))
    return None


def _find_account(text: str) -> Optional[str]:
    patterns = [
        r'(?:account\s*(?:number|no\.?|num\.?|#)|acct\.?\s*(?:no\.?|num\.?|#)?)\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-\.]{3,19})',
        r'(?:invoice\s*(?:number|no\.?|#))\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-\.]{3,19})',
        r'(?:customer\s*(?:id|number|no\.?|#))\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-\.]{3,19})',
        r'(?:policy\s*(?:number|no\.?|#))\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-\.]{3,19})',
        r'(?:member\s*(?:id|number|no\.?|#))\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-\.]{3,19})',
        r'(?:subscriber\s*(?:id|#))\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-\.]{3,19})',
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            val = m.group(1).strip()
            if 4 <= len(val) <= 20:
                return val
    return None


def _find_provider(text: str, filename: str) -> Optional[str]:
    known = re.search(
        r'\b(AT&T|Verizon(?:\s+Wireless)?|Comcast|Xfinity|T-Mobile|Sprint|'
        r'Charter|Spectrum|Cox\s+Communications|CenturyLink|Lumen|Frontier|'
        r'Pacific\s+Gas\s+and\s+Electric|PG&E|Con\s*Edison|ConEd|'
        r'Duke\s+Energy|Dominion\s+Energy|Xcel\s+Energy|Eversource|'
        r'Entergy|Ameren|Evergy|AEP|FirstEnergy|Exelon|Southern\s+Company|'
        r'American\s+Water|Aqua\s+(?:America|Water)|Veolia|United\s+Water|LADWP|'
        r'Kaiser\s+Permanente|Aetna|BlueCross\s+BlueShield|Blue\s+Cross|'
        r'Cigna|Humana|UnitedHealth(?:care)?|Anthem|'
        r'CVS|Walgreens|LabCorp|Quest\s+Diagnostics|'
        r'Amazon|Apple|Google|Netflix|Hulu|Spotify|Adobe|Microsoft|'
        r'Chase|Bank\s+of\s+America|Wells\s+Fargo|Citibank|Capital\s+One|Discover)\b',
        text[:600], re.IGNORECASE
    )
    if known:
        return known.group(1)

    lines = [l.strip() for l in text.split('\n')[:25] if l.strip()]
    candidates = [
        l for l in lines
        if 4 < len(l) < 70
        and not re.match(r'^[\d\s\-/,\.\$]+$', l)
        and not re.search(r'\d{5}', l)
        and not re.search(r'\d{1,2}[/\-]\d{1,2}', l)
        and not re.search(r'page\s+\d', l, re.I)
        and not re.search(r'^\s*p\.?\s*o\.?\s*box', l, re.I)
    ]
    if candidates:
        return max(candidates[:5], key=len)

    name = re.sub(r'\.pdf$', '', filename, flags=re.IGNORECASE)
    name = re.sub(r'[_\-]', ' ', name).strip()
    return name.title() if name else None


def _find_category(provider: Optional[str], text: str) -> Optional[str]:
    combined = ((provider or '') + ' ' + text[:400]).lower()
    if re.search(r'\b(electric|electricity|gas\s+and\s+electric|water\s+dept|water\s+department|'
                 r'utility|utilities|power|energy|sewer|trash|waste|sanitation|'
                 r'pge|pg&e|ladwp|con\s*ed)\b', combined):
        return 'Utilities'
    if re.search(r'\b(hospital|medical\s+center|clinic|health\s+(?:system|care|plan)|'
                 r'doctor|dental|vision|pharmacy|rx|lab(?:oratory|corp)?|radiology|'
                 r'urgent\s*care|physician|surgery|kaiser|aetna|cigna|humana|anthem|'
                 r'bluecross|quest\s+diagnostics|explanation\s+of\s+benefits)\b', combined):
        return 'Medical'
    if re.search(r'\b(rent|lease|apartment|housing|landlord|property\s+management|hoa)\b', combined):
        return 'Rent'
    if re.search(r'\b(phone|mobile|wireless|cellular|internet|cable|broadband|'
                 r'at&t|verizon|t-mobile|comcast|xfinity|spectrum|cox|charter|'
                 r'centurylink|frontier)\b', combined):
        return 'Telecom'
    if re.search(r'\b(credit\s+card|loan|mortgage|auto\s+loan|student\s+loan|'
                 r'line\s+of\s+credit|chase|bank\s+of\s+america|wells\s+fargo|'
                 r'capital\s+one|discover)\b', combined):
        return 'Finance'
    if re.search(r'\b(auto\s+insurance|homeowner|renters\s+insurance|life\s+insurance|'
                 r'property\s+insurance|premium\s+due|policy\s+number)\b', combined):
        return 'Insurance'
    if re.search(r'\b(subscription|software|saas|adobe|microsoft\s+365|'
                 r'google\s+(?:one|workspace)|amazon\s+prime|netflix|hulu|spotify)\b', combined):
        return 'Subscription'
    return None


# ── Main entry point ──────────────────────────────────────────────────────────

def extract_bill_fields(pdf_bytes: bytes, filename: str = '') -> dict:
    """
    Extract bill fields from PDF bytes.
    Returns dict with keys: provider, account_number, amount_due,
    statement_date, due_date, category, _method, _detected_fields.
    Values are None if not found.
    """
    result = {
        'provider':         None,
        'account_number':   None,
        'amount_due':       None,
        'statement_date':   None,
        'due_date':         None,
        'category':         None,
        '_method':          None,
        '_detected_fields': [],
    }

    try:
        raw_text, method = get_text(pdf_bytes)
        result['_method'] = method

        if not raw_text.strip():
            logger.warning('No text extracted from PDF (filename=%s)', filename)
            return result

        # Normalise OCR word-break noise before parsing
        text = _normalise(raw_text)

        amt = _find_amount(text)
        if amt:
            result['amount_due'] = amt
            result['_detected_fields'].append('amount_due')

        due = _find_date(text, [
            'due date', 'payment due date', 'payment due', 'pay by',
            'payment by', 'due on or before', 'please pay by',
            'must be received by', 'due on',
        ])
        if due:
            result['due_date'] = due
            result['_detected_fields'].append('due_date')

        stmt = _find_date(text, [
            'statement date', 'billing date', 'invoice date', 'bill date',
            'date of service', 'service date', 'period ending',
            'billing period end', 'date issued',
        ])
        if stmt:
            result['statement_date'] = stmt
            result['_detected_fields'].append('statement_date')

        acct = _find_account(text)
        if acct:
            result['account_number'] = acct
            result['_detected_fields'].append('account_number')

        provider = _find_provider(text, filename)
        if provider:
            result['provider'] = provider
            result['_detected_fields'].append('provider')

        category = _find_category(provider, text)
        if category:
            result['category'] = category
            result['_detected_fields'].append('category')

        logger.info('Extracted %s via %s from %s',
                    result['_detected_fields'], method, filename or '(upload)')

    except Exception as e:
        logger.error('extract_bill_fields error (file=%s): %s', filename, e, exc_info=True)

    return result
