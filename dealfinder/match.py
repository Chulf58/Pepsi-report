"""Which offers count as plain Pepsi Max or Cult Energy, and which dealers are Danish chains."""

import json
import re

from .parse import parse_packs
from .sources import NEMLIG_MAX_IDS, NEMLIG_PASSES

PEPSI_MAX = "Pepsi Max"
CULT = "Cult Energy"

KEEP = "keep"
REJECT = "reject"
QUARANTINE = "quarantine"
VARIANTS = "variants"
UNRELATED = "not Pepsi Max or Cult Energy"
VARIANTS_NOTE = "variants, Max likely"

FLAVOURS = (
    "lime", "cherry", "kirsebær", "mango", "raspberry", "hindbær", "vanilla", "vanilje",
    "ginger", "ingefær", "lemon", "citron", "citrus", "peach", "fersken", "blueberry",
    "blåbær", "strawberry", "jordbær", "ananas", "pineapple", "twist", "mojito",
)
_FLAVOUR = re.compile(r"\b(%s)\b" % "|".join(FLAVOURS))
_FLAVOUR_BEFORE = re.compile(r"\b(%s)\s+$" % "|".join(FLAVOURS))
_PEPSI_MAX = re.compile(r"\bpepsi[\s-]*max\b")
_SEVERAL = re.compile(r"flere varianter|udvalgte varianter|alle varianter|frit valg")
# What may follow "Pepsi Max" in a plain row, up to the end of that phrase: sizes, pack
# and container words, and connectors that start a mixed row ("eller Faxe Kondi").
_SIZE_TOKEN = re.compile(r"^\d+([.,]\d+)?(cl|ml|l|ltr|liter)?$|^\d+x\d+([.,]\d+)?(cl|ml|l)?$")
_PACK_WORDS = frozenset((
    "x", "à", "cl", "ml", "l", "ltr", "liter", "stk", "ds", "dåse", "dåser", "can", "cans",
    "pk", "pakke", "kasse", "ks", "pet", "flaske", "flasker", "fl", "sodavand", "zero",
    "sugar", "original",
))
_CONNECTORS = frozenset(("eller", "el", "og", "samt", "or", "and", ","))
_PHRASE_END = re.compile(r"\n|[|;!]|\.(\s|$)")


def _flavour_of_pepsi_max(t, mention):
    """The flavour word that belongs to one 'Pepsi Max' mention, or None.

    Only the Pepsi phrase counts: the words up to the first connector or phrase end, and a
    flavour word directly in front. "Pepsi Max eller Faxe Kondi med citron" names a flavour
    for Faxe Kondi, not for Pepsi Max; "Pepsi Max Lime" is flavoured.
    """
    tail = t[mention.end():]
    end = _PHRASE_END.search(tail)
    phrase = tail[:end.start()] if end else tail
    phrase = re.split(r"(?:^|\s)(?:eller|el|og|samt|or|and)\s|,", phrase, maxsplit=1)[0]
    found = _FLAVOUR.search(phrase) or _FLAVOUR_BEFORE.search(t[:mention.start()])
    return found.group(1) if found else None


def _untied_flavour(t, maxes):
    """A flavour word in a clause that names no Pepsi Max, or None.

    "Pepsi Max eller Faxe Kondi. Flere varianter. Fx lime." can mean "for example lime",
    so the row may be Pepsi Max Lime. A flavour in the same clause as a Pepsi Max mention
    ("... Faxe Kondi med citron") belongs to the product named there and does not count.
    """
    segments, start = [], 0
    for m in _PHRASE_END.finditer(t):
        segments.append((start, m.start()))
        start = m.end()
    segments.append((start, len(t)))
    for first, last in segments:
        if not any(first <= mm.start() < last for mm in maxes):
            found = _FLAVOUR.search(t[first:last])
            if found:
                return found.group(1)
    return None


def _max_phrase_is_plain(tail):
    """True when the words after one 'Pepsi Max' are only sizes, pack words or a connector."""
    end = _PHRASE_END.search(tail)
    phrase = tail[:end.start()] if end else tail
    tokens = re.sub(r"[*/+&()\-:]", " ", phrase).replace(",", " , ").split()
    for tok in tokens:
        tok = tok.strip(".")
        if tok in _CONNECTORS:
            return True
        if not tok or tok in _PACK_WORDS or _SIZE_TOKEN.match(tok):
            continue
        return False
    return True


# Tjek's dealer country is "DK" for German border shops with Danish flyers (BorderShop,
# Poetzsch Padborg, fakta Tyskland, Nielsen Scan-Shop, Calle, Fleggaard), so the country
# field is necessary but not enough. A dealer must also be on this list of chains with
# shops in Denmark. Unknown dealers are excluded and listed in the report.
DANISH_CHAIN_NAMES = (
    "Netto", "føtex", "Bilka", "Bilka ToGo", "Salling", "REMA 1000", "Lidl",
    "365discount", "Coop 365", "Kvickly", "SuperBrugsen", "Brugsen", "Dagli'Brugsen",
    "MENY", "SPAR", "Min Købmand", "Løvbjerg", "nemlig.com", "ABC Lavpris", "Let-Køb",
    "Coop.dk",
)
DANISH_CHAINS = frozenset(name.lower() for name in DANISH_CHAIN_NAMES)


def is_danish_dealer(name, country):
    return country == "DK" and (name or "").strip().lower() in DANISH_CHAINS


def _norm(text):
    return re.sub(r"[ \t\r]+", " ", (text or "").lower())  # keep newlines: they end a phrase


def classify_product(text, variant=None):
    """Return (status, product, reason) for one offer's text.

    variant is REMA's text after the slash in its underline ("LIME", "6 PK."), when known.
    """
    t = _norm(text)
    if re.search(r"\bpepsi\b", t):
        if re.search(r"\b(sirup|syrup|sodastream)\b", t):
            return REJECT, None, "syrup, not a ready drink"
        flavour = _FLAVOUR.search(t + " " + _norm(variant))
        maxes = list(_PEPSI_MAX.finditer(t))
        if maxes:
            named = _FLAVOUR.search(_norm(variant)) or next(
                (f for f in (_flavour_of_pepsi_max(t, m) for m in maxes) if f), None)
            if named:
                return REJECT, None, "flavour named (%s)" % (
                    named if isinstance(named, str) else named.group(1))
            untied = _untied_flavour(t, maxes)
            if untied:
                return QUARANTINE, PEPSI_MAX, (
                    "flavour word (%s) in a later clause that names no product" % untied)
            tails = [t[m.end():] for m in maxes]
            if variant:
                tails = [tail + " " + _norm(variant) for tail in tails]
            if any(_max_phrase_is_plain(tail) for tail in tails):
                return KEEP, PEPSI_MAX, None
            return QUARANTINE, PEPSI_MAX, "unexplained words after 'Pepsi Max'"
        if _SEVERAL.search(t) and not flavour:
            return VARIANTS, PEPSI_MAX, VARIANTS_NOTE
        return REJECT, None, "regular Pepsi, not Pepsi Max"
    if re.search(r"\bcult\b", t):
        if "shaker" in t:
            return REJECT, None, "Cult Shaker is a soft drink, not Cult Energy"
        if re.search(r"\benergy\b", t):
            return KEEP, CULT, None
        if not parse_packs(text).packs:
            return REJECT, None, "Cult item without a drink size"
        return QUARANTINE, CULT, "Cult drink without 'Energy' in the text"
    return REJECT, None, UNRELATED


SOURCES = ("tjek", "rema", "nemlig")


def load_known_ids(path):
    """Confirmed product ids per source and product from data/products.json."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    known = {}
    for source in SOURCES:
        entry = data.get(source, {})
        if not isinstance(entry, dict):
            raise ValueError("%s: %r must map product names to id lists" % (path, source))
        known[source] = {}
        for product in (PEPSI_MAX, CULT):
            ids = entry.get(product, [])
            if not isinstance(ids, list) or not all(isinstance(i, str) and i for i in ids):
                raise ValueError("%s: %s/%s must be a list of id strings" % (path, source, product))
            known[source][product] = set(ids)
        both = known[source][PEPSI_MAX] & known[source][CULT]
        if both:
            raise ValueError("%s: %s ids listed under both products: %s"
                             % (path, source, ", ".join(sorted(both))))
    nemlig = known["nemlig"][PEPSI_MAX] | known["nemlig"][CULT]
    if len(nemlig) * NEMLIG_PASSES > NEMLIG_MAX_IDS:
        raise ValueError("%s: %d nemlig ids need %d product requests (this week and next), "
                         "more than the cap of %d requests per run"
                         % (path, len(nemlig), len(nemlig) * NEMLIG_PASSES, NEMLIG_MAX_IDS))
    return known


def classify_with_ids(known, source, product_id, text, variant=None):
    """(status, product, reason, matched_by): a confirmed id wins over the text rules."""
    for product, ids in (known.get(source) or {}).items():
        if product_id in ids:
            return KEEP, product, None, "id"
    status, product, reason = classify_product(text, variant)
    return status, product, reason, "text"
