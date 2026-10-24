"""Turn raw Tjek offers and REMA products into validated observations or quarantine rows."""

import math
from collections import Counter
from dataclasses import dataclass, field, replace

from .history import Observation, dedupe
from .match import KEEP, QUARANTINE, UNRELATED, VARIANTS, classify_with_ids, is_danish_dealer
from .parse import (BOTTLE, PackParse, container_kind, copenhagen_date, pant_per_container, pant_status,
                    pack_tied_to, parse_packs, parse_stated_kr_per_l, resolve_volume)


UPCOMING_NOTE = "next week, nemlig slot"
PEPSI_MAX_NAME = r"pepsi[\s-]*max"


class RowError(ValueError):
    """One API row is malformed; it is reported and the run carries on."""


@dataclass
class Quarantined:
    product: str
    source: str
    source_id: str
    store: str
    description: str
    price_dkk: float | None
    valid_from: str
    valid_to: str
    url: str
    reason: str


@dataclass
class Outcome:
    observations: list = field(default_factory=list)
    # "variants, Max likely" rows: listed in the report, never written to history.
    variants: list = field(default_factory=list)
    quarantined: list = field(default_factory=list)
    rejected: Counter = field(default_factory=Counter)
    excluded_dealers: Counter = field(default_factory=Counter)
    row_errors: list = field(default_factory=list)
    expired: int = 0
    unrelated: int = 0
    bottles_dropped: int = 0
    bottles_by_store: Counter = field(default_factory=Counter)
    out_of_stock: int = 0
    # Confirmed ids per source and product (data/products.json).
    known: dict = field(default_factory=dict)
    # (source, product id, store, text) of listed rows that matched by text, not by id.
    text_matched: list = field(default_factory=list)
    # Next week's nemlig prices that differ from this week's: listed, never written to history.
    upcoming: list = field(default_factory=list)
    # Counts from the next-week nemlig pass (rejected, expired, bottles, ...), kept apart
    # from the main counters so the same product is not counted twice.
    next_week: Counter = field(default_factory=Counter)

    def drop_bottle(self, store):
        self.bottles_dropped += 1
        self.bottles_by_store[store] += 1

    def reject(self, reason):
        if reason == UNRELATED:
            self.unrelated += 1
        else:
            self.rejected[reason] += 1


def _pack_text(vol, packs):
    for p in packs:
        if p.count > 1 and abs(p.total_l - vol) <= 0.01 * vol:
            return "%d x %g L cans" % (p.count, p.unit_l)
    return "%g L can" % vol


def _field_sizes(quantity):
    """(pack volume, unit size) in litres from Tjek's quantity fields; None when unusable."""
    try:
        unit = quantity["unit"]
        size, pieces = quantity["size"], quantity["pieces"]
        if unit is None or unit["si"]["symbol"] != "l":
            return None, None
        if size["from"] != size["to"]:
            return None, None
        unit_l = round(size["from"] * unit["si"]["factor"], 4)
        if pieces["from"] != pieces["to"]:
            return None, unit_l
        vol = round(unit_l * pieces["from"], 4)
    except (KeyError, TypeError):
        return None, None
    return (vol if 0.1 <= vol <= 50 else None), (unit_l if unit_l > 0 else None)


def _remove_pant(price, text, packs):
    """Return (price excluding pant, None) or (None, reason).

    A price that does not mention pant is taken as excluding it: Danish shops advertise
    prices without pant and add "+ pant" (or nothing), so only "inkl. pant" changes it.
    """
    if pant_status(text) != "incl":
        return price, None
    distinct = {(p.count, p.unit_l) for p in packs if not p.total_note}
    if len(distinct) != 1:
        return None, "price includes pant and the can count is unclear"
    count, unit_l = distinct.pop()
    rate = pant_per_container(unit_l, container_kind(text, [unit_l]))
    if rate is None:
        return None, "price includes pant and the container is unclear"
    return round(price - count * rate, 2), None


def _positive(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value > 0)


def _mapping(value, what):
    """value as a dict; None counts as empty. Any other shape is a row error."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise RowError("%s is %s, not an object" % (what, type(value).__name__))
    return value


def _number_or_none(value):
    return value if _positive(value) else None


def _accept(outcome, status, obs, matched_by):
    (outcome.variants if status == VARIANTS else outcome.observations).append(obs)
    if matched_by == "text":
        entry = (obs.source, obs.product_id, obs.store, obs.description)
        if entry not in outcome.text_matched:
            outcome.text_matched.append(entry)


def _tjek_row(o, today, run_id, outcome):
    if not isinstance(o.get("id"), str) or not o["id"]:
        raise RowError("missing offer id")
    dealer = o.get("dealer")
    if not isinstance(dealer, dict):
        raise RowError("missing dealer")
    store = dealer.get("name") or ""
    if not isinstance(store, str):
        raise RowError("dealer name is not text")
    country = _mapping(dealer.get("country"), "dealer.country").get("id")
    if not is_danish_dealer(store, country):
        outcome.excluded_dealers[store or "(no dealer)"] += 1
        return
    valid_from = copenhagen_date(o.get("run_from"))
    valid_to = copenhagen_date(o.get("run_till"))
    if valid_to < today:
        outcome.expired += 1
        return
    heading, description = o.get("heading") or "", o.get("description") or ""
    if not isinstance(heading, str) or not isinstance(description, str):
        raise RowError("heading or description is not text")
    text = "%s\n%s" % (heading, description)
    status, product, reason, matched_by = classify_with_ids(outcome.known, "tjek", o["id"], text)
    if status not in (KEEP, QUARANTINE, VARIANTS):
        outcome.reject(reason)
        return
    url = _mapping(o.get("links"), "links").get("webshop") or dealer.get("website") or ""
    if not isinstance(url, str):
        raise RowError("link is not text")
    pricing = _mapping(o.get("pricing"), "pricing")
    price = pricing.get("price")
    flat = text.replace("\n", " | ")

    def quarantine(why):
        outcome.quarantined.append(Quarantined(
            product or "", "tjek", o["id"], store, flat, price, valid_from.isoformat(),
            valid_to.isoformat(), url, why))

    packs = parse_packs(text)
    if status == KEEP and len(packs.volumes) > 1 and not packs.ambiguous:
        # A mixed flyer row: use the pack written directly before "Pepsi Max".
        tied = pack_tied_to(text, PEPSI_MAX_NAME)
        if tied:
            packs = PackParse([tied], None)
    field_vol, field_unit = _field_sizes(o.get("quantity"))
    # Tjek's quantity fields are noisy (792 cl for a 24-can case); use them only when
    # the text names no size.
    units = packs.container_sizes or ([field_unit] if field_unit else [])
    container = container_kind(text, units)
    if container == BOTTLE:
        outcome.drop_bottle(store)
        return
    if status == QUARANTINE:
        quarantine(reason)
        return
    if container is None:
        quarantine("container unknown (can or bottle)")
        return
    if not _positive(price) or pricing.get("currency") != "DKK":
        quarantine("no usable DKK price")
        return
    if packs.ambiguous:
        quarantine(packs.ambiguous)
        return
    price_ex, why = _remove_pant(price, text, packs.packs)
    if why:
        quarantine(why)
        return
    if not _positive(price_ex):
        quarantine("price %.2f is not positive after pant is taken off" % price_ex)
        return
    vol, why = resolve_volume(price_ex, packs.volumes, field_vol,
                              parse_stated_kr_per_l(description))
    if why:
        quarantine(why)
        return
    kr = round(price_ex / vol, 2)
    if not _positive(kr):
        quarantine("kr/L %r is not positive" % kr)
        return
    _accept(outcome, status, Observation(
        run_id=run_id, run_date=today.isoformat(), product=product, source="tjek",
        source_id=o["id"], product_id=o["id"], store=store, description=flat, pack=_pack_text(vol, packs.packs),
        volume_l=vol, price_dkk=price_ex, kr_per_l=kr, valid_from=valid_from.isoformat(),
        valid_to=valid_to.isoformat(), campaign=True, url=url), matched_by)


def normalize_tjek(offers, today, run_id, outcome):
    for o in offers:
        try:
            _tjek_row(o, today, run_id, outcome)
        except ValueError as e:  # RowError, or a bad timestamp from copenhagen_date
            outcome.row_errors.append(("Tjek", "offer %s skipped: %s" % (o.get("id"), e)))


def _rema_price(p, pr, status, product, reason, matched_by, text, packs, today, run_id, outcome):
    pr = _mapping(pr, "price entry")
    valid_from = copenhagen_date(pr.get("starting_at"))
    valid_to = copenhagen_date(pr.get("ending_at"))
    if valid_to < today:
        outcome.expired += 1
        return
    shown_to = "" if valid_to.year >= 2099 else valid_to.isoformat()
    source_id = "%s@%s" % (p["id"], valid_from.isoformat())
    url = "https://shop.rema1000.dk/varer/%s" % p["id"]
    price = pr.get("price")
    deposit = pr.get("deposit")

    def quarantine(why):
        outcome.quarantined.append(Quarantined(
            product or "", "rema", source_id, "REMA 1000", text, price,
            valid_from.isoformat(), shown_to, url, why))

    counts = {pk.count for pk in packs.containers}
    per_unit = deposit / counts.pop() if _positive(deposit) and len(counts) == 1 else None
    container = container_kind(text, packs.container_sizes, per_unit)
    if container == BOTTLE:
        outcome.drop_bottle("REMA 1000")
        return
    if status == QUARANTINE:
        quarantine(reason)
        return
    if container is None:
        quarantine("container unknown (can or bottle)")
        return
    if not _positive(price):
        quarantine("no usable price")
        return
    if packs.ambiguous:
        quarantine(packs.ambiguous)
        return
    stated = (_number_or_none(pr.get("compare_unit_price"))
              if pr.get("compare_unit") == "ltr" else None)
    price_ex = price
    vol, why = resolve_volume(price, packs.volumes, None, stated)
    if why and stated and _positive(deposit) and _positive(price - deposit):
        # REMA prices exclude deposit today; accept a price that only matches its own
        # litre price once the deposit is taken off.
        vol2, why2 = resolve_volume(round(price - deposit, 2), packs.volumes, None, stated)
        if not why2:
            vol, why, price_ex = vol2, None, round(price - deposit, 2)
    if why:
        quarantine(why)
        return
    kr = round(price_ex / vol, 2)
    if not _positive(kr):
        quarantine("kr/L %r is not positive" % kr)
        return
    _accept(outcome, status, Observation(
        run_id=run_id, run_date=today.isoformat(), product=product, source="rema",
        source_id=source_id, product_id=str(p["id"]), store="REMA 1000", description=text,
        pack=_pack_text(vol, packs.packs), volume_l=vol, price_dkk=price_ex, kr_per_l=kr,
        valid_from=valid_from.isoformat(), valid_to=shown_to,
        campaign=bool(pr.get("is_campaign")), url=url), matched_by)


def normalize_rema(products, today, run_id, outcome):
    for p in products:
        pid = p.get("id") if isinstance(p, dict) else None
        if pid in (None, ""):
            outcome.row_errors.append(("REMA", "product skipped: missing id"))
            continue
        name, underline = p.get("name") or "", p.get("underline") or ""
        if not isinstance(name, str) or not isinstance(underline, str):
            outcome.row_errors.append(("REMA", "product %s skipped: name is not text" % pid))
            continue
        variant = underline.split("/", 1)[1] if "/" in underline else None
        text = "%s %s" % (name, underline)
        status, product, reason, matched_by = classify_with_ids(
            outcome.known, "rema", str(pid), text, variant)
        if status not in (KEEP, QUARANTINE, VARIANTS):
            outcome.reject(reason)
            continue
        packs = parse_packs(underline)
        prices = p.get("prices") or []
        if not isinstance(prices, list):
            outcome.row_errors.append(("REMA", "product %s skipped: prices is %s, not a list"
                                       % (pid, type(prices).__name__)))
            continue
        for pr in prices:
            try:
                _rema_price(p, pr, status, product, reason, matched_by, text, packs, today,
                            run_id, outcome)
            except ValueError as e:  # a bad or missing timestamp
                outcome.row_errors.append(("REMA", "product %s price skipped: %s" % (pid, e)))


def _nemlig_product(p, today, run_id, outcome, slot="", normal_from=None):
    pid = p.get("Id")
    if not isinstance(pid, str) or not pid:
        raise RowError("missing product id")
    name, description = p.get("Name") or "", p.get("Description") or ""
    if not isinstance(name, str) or not isinstance(description, str):
        raise RowError("name or description is not text")
    text = "%s %s" % (name, description)
    status, product, reason, matched_by = classify_with_ids(outcome.known, "nemlig", pid, text)
    if status not in (KEEP, QUARANTINE, VARIANTS):
        outcome.reject(reason)
        return
    availability = _mapping(p.get("Availability"), "Availability")
    campaign = _mapping(p.get("Campaign"), "Campaign")
    # Only a product nemlig can deliver and has in stock has a price one can pay.
    if not (availability.get("IsAvailableInStock") is True
            and availability.get("IsDeliveryAvailable") is True):
        outcome.out_of_stock += 1
        return
    slug = p.get("Url")
    url = "https://www.nemlig.com/%s" % slug if isinstance(slug, str) and slug else ""
    price = p.get("Price")
    packs = parse_packs(description)

    def quarantine(source_id, why, shown_price=price, valid=("", "")):
        outcome.quarantined.append(Quarantined(
            product or "", "nemlig", source_id, "nemlig.com", text, shown_price, valid[0],
            valid[1], url, why))

    container = container_kind(text, packs.container_sizes)
    if container == BOTTLE:
        outcome.drop_bottle("nemlig.com")
        return
    if status == QUARANTINE:
        quarantine(pid, reason)
        return
    if container is None:
        quarantine(pid, "container unknown (can or bottle)")
        return
    if packs.ambiguous:
        quarantine(pid, packs.ambiguous)
        return
    # nemlig shows "ex. pant"; an unstated pant is taken as excluded as for Tjek.
    if not _positive(price):
        quarantine(pid, "no usable price")
        return
    vol, why = resolve_volume(price, packs.volumes, None, None)
    if why:
        quarantine(pid, why)
        return

    def observe(source_id, pack_price, pack, valid_from, valid_to, is_campaign):
        """pack_price is unrounded; rounding is only for the stored, shown values."""
        shown_price, kr = round(pack_price, 2), round(pack_price / vol, 2)
        if not (_positive(shown_price) and _positive(kr)):
            quarantine(source_id, "price %r gives no usable kr/L" % pack_price, pack_price,
                       (valid_from, valid_to))
            return
        _accept(outcome, status, Observation(
            run_id=run_id, run_date=today.isoformat(), product=product, source="nemlig",
            source_id=source_id, product_id=pid, store="nemlig.com", description=text,
            pack=pack, volume_l=vol, price_dkk=shown_price, kr_per_l=kr,
            valid_from=valid_from, valid_to=valid_to, campaign=is_campaign, url=url, slot=slot),
            matched_by)

    pack = _pack_text(vol, packs.packs)
    # The normal price has no validity dates; it is the price seen on this run's day.
    observe(pid, price, pack, normal_from or today.isoformat(), "", False)
    if not campaign:
        return
    start = copenhagen_date(campaign.get("IntervalStart"))
    end = copenhagen_date(campaign.get("IntervalEnd"))
    if end < today:
        outcome.expired += 1
        return
    source_id = "%s@campaign:%s" % (pid, start.isoformat())
    count, total = campaign.get("MinQuantity"), campaign.get("CampaignPrice")
    if count is None and campaign.get("Type") == "ProductCampaignDiscount":
        # A plain price cut carries no MinQuantity: CampaignPrice is the price of one pack.
        count = 1
    if (campaign.get("VariousPriceProductsCampaign") or not isinstance(count, int)
            or isinstance(count, bool) or count < 1 or not _positive(total)):
        quarantine(source_id, "campaign not understood (%s)" % campaign.get("Type"), total,
                   (start.isoformat(), end.isoformat()))
        return
    # "2 for 80" is 40.00 per pack; kr/L is the same as 80 over both packs.
    label = pack if count == 1 else "%s, %d for %.2f" % (pack, count, total)
    observe(source_id, total / count, label, start.isoformat(), end.isoformat(), True)


def normalize_nemlig(products, today, run_id, outcome, slot="", normal_from=None):
    for p in products:
        try:
            if not isinstance(p, dict):
                raise RowError("product is not an object")
            _nemlig_product(p, today, run_id, outcome, slot, normal_from)
        except ValueError as e:  # RowError, or a bad timestamp from copenhagen_date
            pid = p.get("Id") if isinstance(p, dict) else None
            outcome.row_errors.append(("nemlig", "product %s skipped: %s" % (pid, e)))


def slot_date(slot):
    """The calendar date (YYYY-MM-DD) in a nemlig slot text such as '2026103112-120-240, zone 1'."""
    return "%s-%s-%s" % (slot[:4], slot[4:6], slot[6:8])


def build(tjek_offers, rema_products, today, run_id, nemlig_products=(), known=None,
          nemlig_slot="", nemlig_next=(), nemlig_next_slot=""):
    outcome = Outcome(known=known or {})
    # The same offer comes back from several search centres and queries.
    by_id, no_id = {}, []
    for o in tjek_offers:
        if isinstance(o, dict) and isinstance(o.get("id"), str) and o["id"]:
            by_id.setdefault(o["id"], o)
        else:
            no_id.append(o if isinstance(o, dict) else {})
    normalize_tjek(no_id + list(by_id.values()), today, run_id, outcome)
    normalize_rema(rema_products, today, run_id, outcome)
    normalize_nemlig(nemlig_products, today, run_id, outcome, nemlig_slot)
    if nemlig_next:
        # Next week's slot: keep only what differs from this week. A row cannot start before
        # that slot's date, so a campaign already running is dated from the slot.
        scratch = Outcome(known=outcome.known)
        slot_from = slot_date(nemlig_next_slot)
        normalize_nemlig(nemlig_next, today, run_id, scratch, nemlig_next_slot, slot_from)
        now = {(o.source_id, o.price_dkk) for o in outcome.observations}
        outcome.upcoming = [replace(o, valid_from=max(o.valid_from, slot_from))
                            for o in dedupe(scratch.observations)
                            if (o.source_id, o.price_dkk) not in now]
        # Errors, quarantines and counts from that pass are reported too; its observations
        # never reach history.
        outcome.row_errors += [(src, "next week: " + msg) for src, msg in scratch.row_errors]
        outcome.quarantined += scratch.quarantined
        outcome.next_week.update(
            {"rejected": sum(scratch.rejected.values()), "unrelated": scratch.unrelated,
             "expired": scratch.expired, "bottles dropped": scratch.bottles_dropped,
             "out of stock": scratch.out_of_stock})
    outcome.observations = dedupe(outcome.observations)
    outcome.variants = dedupe(outcome.variants)
    seen, unique = set(), []
    for q in outcome.quarantined:
        if (q.source, q.source_id) not in seen:
            seen.add((q.source, q.source_id))
            unique.append(q)
    outcome.quarantined = unique
    return outcome
