"""Pack size, stated litre price and pant parsing for Danish offer text."""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

NUM = r"(\d+(?:[.,]\d+)?)"
UNIT = r"(cl|ml|ltr|liter|litre|l)\.?(?![a-zæøå])"
CONTAINER_COUNT = r"(?:ds|dåser?|stk|fl|flasker?)\b"

_TO_LITRES = {"cl": 0.01, "ml": 0.001, "ltr": 1.0, "liter": 1.0, "litre": 1.0, "l": 1.0}

# "1 l = 5,33 DKK" is a litre price, not a pack size.
_PER_LITRE_NOISE = re.compile(r"\b1\s*l\s*=", re.I)
_RANGE = re.compile(NUM + r"\s*-\s*" + NUM + r"\s*" + UNIT, re.I)
_ALT_COUNTS = re.compile(r"/\s*\d+\s*/\s*\d+\s*" + CONTAINER_COUNT, re.I)
_MULTI = re.compile(r"(\d+)\s*[x×*]\s*" + NUM + r"\s*" + UNIT, re.I)
_SIZE_SLASH_COUNT = re.compile(NUM + r"\s*" + UNIT + r"\s*/\s*(\d+)\s*" + CONTAINER_COUNT, re.I)
_TOTAL_SLASH_PK = re.compile(NUM + r"\s*" + UNIT + r"\s*/\s*(\d+)\s*pk\b", re.I)
_NOTE_BEFORE = re.compile(r"\(\s*$")
_NOTE_AFTER = re.compile(r"\s*\)|\s*i alt\b", re.I)
_SINGLE = re.compile(r"(?<![\d.,])" + NUM + r"\s*" + UNIT, re.I)

_STATED = [
    re.compile(r"(?:pr\.?\s*(?:liter|ltr\.?|l\b)|literpris|liter\s*=\s*kr\.?|\b1\s*l\s*=)"
               r"\s*(max\.?\s*)?" + NUM, re.I),
    re.compile(r"()/\s*" + NUM + r"\s*pr\.?\s*liter", re.I),
    re.compile(r"()(?<![/\d.,])" + NUM + r"\s*pr\.?\s*liter", re.I),
]

CAN = "can"
BOTTLE = "bottle"
_CAN_WORDS = re.compile(r"\b(ds|dåse|dåser|can|cans)\b", re.I)
_BOTTLE_WORDS = re.compile(r"\b(pet|plast|plastflaske|fl|flaske|flasker|glas)\b", re.I)

# Deposit for a can (Dansk Retursystem class A). It matches the deposit REMA's API
# reports for a 33 cl can, 1.00 kr. Bottles are dropped before pant matters.
PANT_CAN = 1.0
# REMA deposit per item that only a small PET bottle carries (class B).
PANT_SMALL_PET = 1.5

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    try:
        COPENHAGEN = ZoneInfo("Europe/Copenhagen")
    except ZoneInfoNotFoundError:
        COPENHAGEN = None
except ImportError:
    COPENHAGEN = None
# Shown in the run summary when the tz database is missing and the fixed rule is used.
TZ_NOTE = None if COPENHAGEN else (
    "tz database missing: Danish dates use the fixed EU rule (UTC+2 from the last Sunday "
    "of March 01:00 UTC to the last Sunday of October 01:00 UTC, else UTC+1)")


def _num(s):
    return float(s.replace(",", "."))


def _litres(value, unit):
    return round(_num(value) * _TO_LITRES[unit.lower()], 4)


@dataclass(frozen=True)
class Pack:
    count: int
    unit_l: float
    # A bracketed size after a multipack, such as "(7,92 l)" after "24 x 0,33 l": it states
    # the pack total, not a container. When it disagrees with the multipack total it still
    # counts as a volume, so the row is quarantined as several pack sizes.
    total_note: bool = False

    @property
    def total_l(self):
        return round(self.count * self.unit_l, 4)


@dataclass
class PackParse:
    packs: list
    ambiguous: str | None

    @property
    def containers(self):
        """Packs that describe real containers, total-volume notes left out."""
        return [p for p in self.packs if not p.total_note]

    @property
    def container_sizes(self):
        return [p.unit_l for p in self.containers]

    @property
    def volumes(self):
        """Distinct total pack volumes in litres, in order of appearance."""
        out = []
        for p in self.packs:
            if not any(abs(p.total_l - v) <= 0.01 * v for v in out):
                out.append(p.total_l)
        return out


def parse_packs(text):
    """Find pack sizes in offer text; flag ranges and alternative counts as ambiguous."""
    text = _PER_LITRE_NOISE.sub(" ", text or "")
    ambiguous = None
    if _RANGE.search(text):
        ambiguous = "size range in text (%s)" % _RANGE.search(text).group(0)
    elif _ALT_COUNTS.search(text):
        ambiguous = "alternative pack counts in text (%s)" % _ALT_COUNTS.search(text).group(0).strip()
    packs = []
    spans = []

    def taken(m):
        return any(m.start() < e and s < m.end() for s, e in spans)

    for m in _MULTI.finditer(text):
        packs.append((m.start(), Pack(int(m.group(1)), _litres(m.group(2), m.group(3)))))
        spans.append(m.span())
    for m in _SIZE_SLASH_COUNT.finditer(text):
        if not taken(m):
            packs.append((m.start(), Pack(int(m.group(3)), _litres(m.group(1), m.group(2)))))
            spans.append(m.span())
    for m in _TOTAL_SLASH_PK.finditer(text):
        if not taken(m):
            count = int(m.group(3))
            total = _litres(m.group(1), m.group(2))
            packs.append((m.start(), Pack(count, round(total / count, 4) if count else 0.0)))
            spans.append(m.span())
    for m in _SINGLE.finditer(text):
        if not taken(m) and not _RANGE.search(text[max(0, m.start() - 8):m.end()]):
            # Only a bracketed size that follows a multipack is a total; "Pepsi Max (0,33 l)"
            # on its own is a real can size.
            note = bool(_NOTE_BEFORE.search(text[:m.start()]) and _NOTE_AFTER.match(text[m.end():])
                        and any(start < m.start() and pk.count > 1 for start, pk in packs))
            packs.append((m.start(), Pack(1, _litres(m.group(1), m.group(2)), note)))
            spans.append(m.span())
    packs.sort(key=lambda t: t[0])
    return PackParse([p for _, p in packs if p.count > 0 and p.unit_l > 0], ambiguous)


# Between a pack ("24x33 cl") and the product it belongs to, a flyer may only put container
# words and punctuation: "24x33 cl. ds. Pepsi Max".
_BETWEEN_PACK_AND_NAME = re.compile(r"^[\s.,]*(?:(?:ds|dåser?|can|cans)\b[\s.,]*)*$", re.I)


def pack_tied_to(text, name):
    """The one multipack written directly before every mention of name, else None.

    Used for a mixed flyer row that lists several packs for several products ("18x33 cl. ds.
    Royal Export ... 24x33 cl. ds. Pepsi Max ..."). Every mention of name must have its own
    "N x size" directly in front of it, and all of them must agree. A pack that only comes
    after the name, or one with other words in between, is not tied and gives None.
    """
    text = _PER_LITRE_NOISE.sub(" ", text or "")
    packs = [(m.end(), Pack(int(m.group(1)), _litres(m.group(2), m.group(3))))
             for m in _MULTI.finditer(text)]
    tied = []
    for mention in re.finditer(name, text, re.I):
        before = [(end, pk) for end, pk in packs if end <= mention.start()]
        if not before:
            return None
        end, pk = before[-1]
        if not _BETWEEN_PACK_AND_NAME.match(text[end:mention.start()]):
            return None
        tied.append(pk)
    if not tied or any(pk != tied[0] for pk in tied):
        return None
    return tied[0]


def parse_stated_kr_per_l(text):
    """The litre price printed in the offer text, or None when absent or only an upper bound."""
    text = text or ""
    for pattern in _STATED:
        m = pattern.search(text)
        if m:
            if m.group(1):
                return None  # "Pr. liter max. 12.63": bound across variants, not this pack
            return _num(m.group(2))
    return None


def pant_status(text):
    """'incl' when the price includes pant, 'excl' when the text says it does not, else 'unstated'."""
    t = (text or "").lower()
    if re.search(r"\b(inkl|incl|inklusiv|inklusive)\.?\s*(af\s*)?pant", t):
        return "incl"
    if re.search(r"\+\s*pant|\b(ex|excl|ekskl|eksl|exkl)\.?\s*(pant|embl)|ingen pant|uden pant", t):
        return "excl"
    return "unstated"


def container_kind(text, unit_sizes, deposit_per_unit=None):
    """CAN, BOTTLE, or None when it cannot be settled.

    No can of 1 L or more is sold, so such a size means a bottle. REMA's deposit of 1.50
    per item is only charged on small PET bottles. Under 1 L with no bottle word counts as
    a can (ruling cans-only-under-1-litre-without-bottle-word-counts-as-can). Can and bottle
    words together, or no size at all, stay unknown.
    """
    has_can = bool(_CAN_WORDS.search(text or ""))
    has_bottle = bool(_BOTTLE_WORDS.search(text or "")) or any(u >= 1.0 for u in unit_sizes)
    if deposit_per_unit is not None and abs(deposit_per_unit - PANT_SMALL_PET) < 0.01:
        has_bottle = True
    if has_can and has_bottle:
        return None
    if has_bottle:
        return BOTTLE
    if has_can or unit_sizes:
        return CAN
    return None


def pant_per_container(unit_l, container):
    return PANT_CAN if container == CAN and unit_l < 1.0 else None


def _last_sunday_01_utc(year, month):
    day = datetime(year, month + 1, 1, 1, tzinfo=timezone.utc) - timedelta(days=1)
    return day - timedelta(days=(day.weekday() + 1) % 7)


def fixed_rule_offset_hours(moment):
    """Danish UTC offset by the EU summer-time rule, for use without a tz database."""
    start = _last_sunday_01_utc(moment.year, 3)
    end = _last_sunday_01_utc(moment.year, 10)
    return 2 if start <= moment < end else 1


def copenhagen_date(timestamp):
    """The Danish calendar date of an API timestamp such as 2026-10-22T22:00:00+0000."""
    if not isinstance(timestamp, str):
        raise ValueError("missing timestamp")
    moment = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S%z")
    if COPENHAGEN is not None:
        return moment.astimezone(COPENHAGEN).date()
    utc = moment.astimezone(timezone.utc)
    return (utc + timedelta(hours=fixed_rule_offset_hours(utc))).date()


def _close(a, b, tol):
    return abs(a - b) <= tol * b


def resolve_volume(price, text_volumes, field_volume, stated_kr_per_l):
    """Pick the pack volume in litres, or return (None, reason) for quarantine.

    The text is the primary source; the API's quantity fields are a cross-check and the
    stated litre price, when printed, settles disagreements.
    """
    if len(text_volumes) > 1:
        return None, "several pack sizes in text: %s L" % ", ".join("%g" % v for v in text_volumes)
    candidates = [v for v in text_volumes if v > 0]
    if field_volume and field_volume > 0 and not any(_close(field_volume, v, 0.02) for v in candidates):
        candidates.append(field_volume)
    if not candidates:
        return None, "no pack size found"
    if stated_kr_per_l:
        for v in candidates:
            if _close(price / v, stated_kr_per_l, 0.03):
                return v, None
        return None, "price %.2f does not match stated %.2f kr/L for %s L" % (
            price, stated_kr_per_l, " or ".join("%g" % v for v in candidates))
    if len(candidates) > 1:
        return None, "text says %g L, quantity fields say %g L" % (candidates[0], candidates[1])
    if not text_volumes:
        return None, "pack size only in quantity fields (%g L), not in text" % candidates[0]
    return candidates[0], None
