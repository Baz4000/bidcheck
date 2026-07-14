"""
Bid Checker — Analysis Engine

Analyzes a Kalitta bid snapshot from one subject pilot's perspective.

  • The subject can be a Captain (CA) or First Officer (FO).
  • If a personal XLS export for the subject is supplied (subject_xls), it's used.
    Otherwise the subject's bid preferences are extracted from the appropriate
    all-bids file (ca_xls or fo_xls). This lets guests view their own status
    without having to upload anything.

Output JSON keys are kept stable (still prefixed `barry_*`) for backwards
compatibility with snapshots stored before this refactor.
"""
import io
import re
import warnings
import logging
from collections import OrderedDict, Counter
from datetime import datetime, timezone

warnings.filterwarnings('ignore')
logging.disable(logging.CRITICAL)


def parse_overview(xlsx_bytes: bytes) -> dict:
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), data_only=True)
    ws = wb.active
    info = {}
    for row in ws.iter_rows(values_only=True):
        name = str(row[0]).strip() if row[0] else ''
        comp = str(row[1]).strip() if row[1] else ''
        if not name or name == 'Line Name':
            continue
        ca_m    = re.search(r'(\d+)\s*CA', comp, re.I)
        fo_m    = re.search(r'(\d+)\s*FO', comp, re.I)
        ca_only = bool(re.search(r'CA\s*ONLY', comp, re.I)) or (ca_m and not fo_m)
        ca_slots = int(ca_m.group(1)) if ca_m else (1 if ca_only else 0)
        fo_slots = int(fo_m.group(1)) if fo_m else 0
        info[name.upper()] = {'ca': ca_slots, 'fo': fo_slots, 'ca_only': bool(ca_only)}
    return info


def build_line_lookup(line_info: dict) -> dict:
    lookup = {}
    for line_name in line_info:
        m = re.search(r'(\d+)', line_name)
        if m:
            lookup[int(m.group(1))] = line_name
    return lookup


def _resolve_line(ln: int, line_lookup: dict) -> str:
    if line_lookup and ln in line_lookup:
        return line_lookup[ln]
    prefix = 'R' if ln > 104 else ('Q' if ln > 88 else 'F')
    return f'{prefix}{ln}'


def parse_bids_xls(xls_bytes: bytes, line_lookup: dict = None) -> OrderedDict:
    import xlrd
    wb = xlrd.open_workbook(file_contents=xls_bytes)
    ws = wb.sheet_by_index(0)
    pilots: OrderedDict = OrderedDict()
    seniority = 0
    current = None
    for r in range(ws.nrows):
        row = [ws.cell_value(r, c) for c in range(ws.ncols)]
        b = str(row[1]).strip() if row[1] != '' else ''
        c = row[2] if len(row) > 2 else ''
        d = row[3] if len(row) > 3 else ''
        if b and b != 'Name' and c == '' and d == '':
            seniority += 1
            current = b
            pilots[current] = {'seniority': seniority, 'choices': []}
        elif current and b == '' and c != '' and d != '':
            try:
                choice = int(float(c))
                ln     = int(float(d))
                pilots[current]['choices'].append({
                    'choice': choice,
                    'line':   _resolve_line(ln, line_lookup),
                })
            except (ValueError, TypeError):
                pass
    return pilots


def parse_barry_xls(xls_bytes: bytes, line_lookup: dict = None) -> list:
    """Parse a single-pilot personal export into an ordered list of line codes."""
    import xlrd
    wb = xlrd.open_workbook(file_contents=xls_bytes)
    ws = wb.sheet_by_index(0)
    bids = {}
    for r in range(ws.nrows):
        row = [ws.cell_value(r, c) for c in range(ws.ncols)]
        c = row[2] if len(row) > 2 else ''
        d = row[3] if len(row) > 3 else ''
        if c != '' and d != '':
            try:
                choice = int(float(c))
                ln     = int(float(d))
                if 1 <= choice <= 200 and 1 <= ln <= 200:
                    bids[choice] = _resolve_line(ln, line_lookup)
            except (ValueError, TypeError):
                pass
    return [bids[k] for k in sorted(bids)]


def _split_name(name: str):
    """Return (last, first_no_initial) lowercased and stripped, or (last, '') if unparseable."""
    parts = (name or '').split(',')
    last = parts[0].strip().lower() if parts else ''
    first = ''
    if len(parts) >= 2:
        first_tokens = parts[1].strip().split()
        if first_tokens:
            first = first_tokens[0].strip().lower()  # drop middle initial
    return last, first


def _find_pilot_key(pilots: OrderedDict, name: str):
    """Locate a pilot in the all-bids dict.

    Match strategy (most specific first):
      1. Exact (case-insensitive) full-name match.
      2. Last + first-name match (ignores middle initials).
      3. Unique last-name substring match.
    Returns None if no candidate or if the last-name match is ambiguous.
    """
    if not name:
        return None

    name_l = name.lower().strip()
    for pilot in pilots:
        if pilot.lower().strip() == name_l:
            return pilot

    last, first = _split_name(name)
    if last and first:
        for pilot in pilots:
            p_last, p_first = _split_name(pilot)
            if p_last == last and p_first == first:
                return pilot

    if last:
        matches = [p for p in pilots if last in p.lower()]
        if len(matches) == 1:
            return matches[0]
        # Ambiguous or none — give up rather than guess wrong
    return None


def _prefs_from_all_bids(pilots: OrderedDict, name: str) -> list:
    """Extract a pilot's bid preferences in priority order from the all-bids dict."""
    key = _find_pilot_key(pilots, name)
    if not key:
        return []
    return [c['line'] for c in sorted(pilots[key]['choices'], key=lambda x: x['choice'])]


def simulate_allocation(ca_pilots, fo_pilots, line_info):
    ca_slots = {ln: d['ca'] for ln, d in line_info.items()}
    fo_slots = {ln: d['fo'] for ln, d in line_info.items()}
    awarded  = {}
    for pilot, data in ca_pilots.items():
        for ch in sorted(data['choices'], key=lambda x: x['choice']):
            if ca_slots.get(ch['line'], 0) > 0:
                ca_slots[ch['line']] -= 1
                awarded[pilot] = ch['line']
                break
    for pilot, data in fo_pilots.items():
        for ch in sorted(data['choices'], key=lambda x: x['choice']):
            ln = ch['line']
            if line_info.get(ln, {}).get('ca_only', False):
                continue
            if fo_slots.get(ln, 0) > 0:
                fo_slots[ln] -= 1
                awarded[pilot] = ln
                break
    return awarded


def build_sim_seats(allocation, ca_pilots, fo_pilots):
    sim_seats = {}
    for pilot, ln in allocation.items():
        if pilot in ca_pilots:
            sen = ca_pilots[pilot]['seniority']
            sim_seats.setdefault(ln, {'ca': [], 'fo': []})['ca'].append((sen, pilot))
        elif pilot in fo_pilots:
            sen = fo_pilots[pilot]['seniority']
            sim_seats.setdefault(ln, {'ca': [], 'fo': []})['fo'].append((sen, pilot))
    for ln in sim_seats:
        sim_seats[ln]['ca'].sort()
        sim_seats[ln]['fo'].sort()
    return sim_seats


def _line_sort_key(line_code: str) -> int:
    """Sort line codes by their numeric component (F1, Q89, R105 → 1, 89, 105)."""
    m = re.search(r'(\d+)', line_code)
    return int(m.group(1)) if m else 9999


def get_full_allocation(ca_xls: bytes, fo_xls: bytes, overview_xlsx: bytes) -> dict:
    """Return the simulated crew allocation for ALL lines — no subject pilot needed.

    Used by the Master Roster view to show who is sitting on every line.

    Returns
    -------
    dict with keys:
        lines           : list of dicts, one per line, sorted numerically
        generated       : UTC timestamp string
        total_lines     : int — lines in the overview
        ca_pilot_count  : int — CAs who submitted bids
        fo_pilot_count  : int — FOs who submitted bids
        ca_allocated    : int — CAs awarded a line
        fo_allocated    : int — FOs awarded a line
        lines_with_crew : int — lines that have at least one assigned pilot
    """
    line_info   = parse_overview(overview_xlsx)
    line_lookup = build_line_lookup(line_info)
    ca_pilots   = parse_bids_xls(ca_xls, line_lookup)
    fo_pilots   = parse_bids_xls(fo_xls, line_lookup)
    allocation  = simulate_allocation(ca_pilots, fo_pilots, line_info)
    sim_seats   = build_sim_seats(allocation, ca_pilots, fo_pilots)

    lines = []
    for line_code in sorted(line_info.keys(), key=_line_sort_key):
        info  = line_info[line_code]
        seats = sim_seats.get(line_code, {'ca': [], 'fo': []})
        ca_crew = [{'seniority': s, 'name': n} for s, n in seats['ca']]
        fo_crew = [{'seniority': s, 'name': n} for s, n in seats['fo']]
        lines.append({
            'line_code':  line_code,
            'ca_only':    info['ca_only'],
            'ca_quota':   info['ca'],
            'fo_quota':   info['fo'],
            'ca_filled':  len(ca_crew),
            'fo_filled':  len(fo_crew),
            'ca_crew':    ca_crew,
            'fo_crew':    fo_crew,
            'is_full':    (len(ca_crew) >= info['ca'] and
                           (info['ca_only'] or len(fo_crew) >= info['fo'])),
            'is_empty':   len(ca_crew) == 0 and len(fo_crew) == 0,
        })

    ca_alloc = sum(1 for p, ln in allocation.items() if p in ca_pilots)
    fo_alloc = sum(1 for p, ln in allocation.items() if p in fo_pilots)

    return {
        'lines':            lines,
        'generated':        datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M'),
        'total_lines':      len(line_info),
        'ca_pilot_count':   len(ca_pilots),
        'fo_pilot_count':   len(fo_pilots),
        'ca_allocated':     ca_alloc,
        'fo_allocated':     fo_alloc,
        'lines_with_crew':  sum(1 for ln in lines if not ln['is_empty']),
    }


def analyze_bids(ca_xls, fo_xls, overview_xlsx,
                 subject_name='Moore, Barry',
                 subject_class='FO',
                 subject_xls=None,
                 # Legacy parameter name — still accepted for backwards compatibility
                 barry_xls=None,
                 barry_name=None):
    """
    Run the full bid simulation and return a per-line analysis from the
    subject pilot's perspective.

    Parameters
    ----------
    ca_xls, fo_xls : bytes
        All-bids XLS exports (everyone's bid preferences).
    overview_xlsx : bytes
        Monthly Overview.xlsx (line complement).
    subject_name : str
        Pilot to analyse from, in "Lastname, Firstname" form.
    subject_class : 'CA' or 'FO'
        Whether the subject is a Captain or First Officer. Drives which pool
        the 'senior not bid' tally is computed against.
    subject_xls : bytes, optional
        The subject's personal XLS export. If supplied, used to read their
        preferences (preserves precise preference order). Otherwise prefs are
        extracted from the appropriate all-bids file.
    barry_xls, barry_name : deprecated
        Old parameter names — still accepted for backwards compatibility.
    """
    # ── Legacy parameter compatibility ────────────────────────────────────────
    if barry_xls is not None and subject_xls is None:
        subject_xls = barry_xls
    if barry_name is not None and subject_name == 'Moore, Barry':
        subject_name = barry_name

    # ── Parse inputs ──────────────────────────────────────────────────────────
    line_info   = parse_overview(overview_xlsx)
    line_lookup = build_line_lookup(line_info)
    ca_pilots   = parse_bids_xls(ca_xls, line_lookup)
    fo_pilots   = parse_bids_xls(fo_xls, line_lookup)

    # ── Subject pilot lookup ──────────────────────────────────────────────────
    pool = ca_pilots if subject_class == 'CA' else fo_pilots
    subject_key = _find_pilot_key(pool, subject_name) or subject_name
    subject_sen = pool.get(subject_key, {}).get('seniority', 0)

    # ── Subject preferences ───────────────────────────────────────────────────
    if subject_xls:
        subject_prefs = parse_barry_xls(subject_xls, line_lookup)
    else:
        subject_prefs = _prefs_from_all_bids(pool, subject_name)

    # ── Senior pilots in the same class who haven't bid yet ───────────────────
    senior_not_bid = sorted(
        [{'seniority': data['seniority'], 'name': name}
         for name, data in pool.items()
         if data['seniority'] < subject_sen and len(data['choices']) == 0],
        key=lambda x: x['seniority']
    )
    senior_label = 'Senior Captains' if subject_class == 'CA' else 'Senior FOs'

    # ── Run the allocation simulation ─────────────────────────────────────────
    allocation = simulate_allocation(ca_pilots, fo_pilots, line_info)
    sim_seats  = build_sim_seats(allocation, ca_pilots, fo_pilots)

    projected = allocation.get(subject_key) or next(
        (ln for p, ln in allocation.items()
         if subject_name.lower().split(',')[0] in p.lower()), None)

    # ── Per-line analysis from subject's viewpoint ────────────────────────────
    is_ca = subject_class == 'CA'
    lines = []
    for rank, line_code in enumerate(subject_prefs, 1):
        info     = line_info.get(line_code, {'ca': 1, 'fo': 1, 'ca_only': False})
        ca_only  = info.get('ca_only', False)
        own_quota = info.get('ca' if is_ca else 'fo', 0)
        seats    = sim_seats.get(line_code, {'ca': [], 'fo': []})
        ca_seats = [{'seniority': s, 'name': n,
                     'is_subject': is_ca and n == subject_key,
                     'is_barry':   is_ca and n == subject_key}
                    for s, n in seats['ca']]
        fo_seats = [{'seniority': s, 'name': n,
                     'is_subject': (not is_ca) and n == subject_key,
                     'is_barry':   (not is_ca) and n == subject_key}
                    for s, n in seats['fo']]
        own_seats = ca_seats if is_ca else fo_seats
        other_seats = fo_seats if is_ca else ca_seats  # noqa: F841
        own_filled = len(own_seats)
        subject_in = any(x['is_subject'] for x in own_seats)
        n_senior   = sum(1 for x in own_seats if x['seniority'] < subject_sen and not x['is_subject'])
        n_junior   = sum(1 for x in own_seats if x['seniority'] > subject_sen)

        # FO viewing a CA-only line: discarded
        # CA viewing any line: CA-only is just a normal CA line, no special case
        if ca_only and not is_ca:
            status, status_text = 'ca-only', 'CA-Only (discarded)'
        elif line_code == projected:
            status, status_text = 'projected', 'PROJECTED AWARD'
        elif subject_in:
            status, status_text = 'winning', f'WINNING ({own_filled}/{own_quota})'
        elif own_filled >= own_quota:
            all_senior = all(x['seniority'] < subject_sen for x in own_seats)
            if all_senior:
                noun = 'CA' if is_ca else 'FO'
                status = 'blocked'
                status_text = f'BLOCKED (all {own_quota} {noun}{"s" if own_quota>1 else ""} senior)'
            else:
                status = 'competitive'
                status_text = f'COMPETITIVE ({n_senior} senior, {n_junior} junior)'
        elif own_filled > 0:
            status, status_text = 'partial', f'PARTIAL ({own_filled}/{own_quota} filled)'
        else:
            status, status_text = 'open', 'OPEN (no bids yet)'

        lines.append({
            'rank': rank, 'line_code': line_code,
            'status': status, 'status_text': status_text,
            'fo_quota': info.get('fo', 0), 'fo_filled': len(fo_seats),
            'ca_quota': info.get('ca', 0), 'ca_filled': len(ca_seats),
            'own_quota': own_quota, 'own_filled': own_filled,
            'n_senior': n_senior, 'n_junior': n_junior,
            'ca_seats': ca_seats, 'fo_seats': fo_seats,
        })

    counts  = Counter(l['status'] for l in lines)
    summary = {
        'projected':   counts.get('projected', 0),
        'winning':     counts.get('winning', 0),
        'blocked':     counts.get('blocked', 0),
        'competitive': counts.get('competitive', 0),
        'partial':     counts.get('partial', 0),
        'open':        counts.get('open', 0),
        'ca_only':     counts.get('ca-only', 0),
    }

    return {
        'generated':            datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M'),
        # New canonical keys
        'subject_name':         subject_key,
        'subject_class':        subject_class,
        'subject_seniority':    subject_sen,
        'senior_not_bid_label': senior_label,
        # Legacy keys — kept stable so existing snapshots and templates keep working
        'barry_name':           subject_key,
        'barry_seniority':      subject_sen,
        'projected_award':      projected or '???',
        'n_prefs':              len(subject_prefs),
        'summary':              summary,
        'senior_not_bid':       senior_not_bid,
        'senior_not_bid_count': len(senior_not_bid),
        'lines':                lines,
    }
