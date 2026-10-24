"""Fetching raw offers from Tjek (eTilbudsavis), REMA 1000 and nemlig.com, live or from fixtures."""

import http.cookiejar
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

# No e-mail address or other personal data goes in the User-Agent.
USER_AGENT = "PepsiReport-dealfinder/0.1 (personal weekly price check; low volume)"
TJEK_URL = "https://api.etilbudsavis.dk/v2/offers/search"
REMA_URL = "https://api.digital.rema1000.dk/api/v3/products"
NEMLIG_BASE = "https://www.nemlig.com"
# Hard cap on nemlig product requests per run (one per id).
NEMLIG_MAX_IDS = 25
# At most 3 queries x 3 centres x 3 pages = 27 requests; a short page stops a centre early.
# "pepsi" finds flyer rows that name Pepsi Max only in the text; regular Pepsi is rejected later.
TJEK_QUERIES = ("pepsi max", "cult", "pepsi")
# Search centres (lat, lng, radius m) covering Jutland and Funen, Zealand and the
# islands, and Bornholm. Single-dealer filtering missed rows (finding
# danish-pepsi-cult-offer-data-sources-tjek-rema-api-october-2026), so search by area.
TJEK_CENTRES = ((56.2, 9.5, 200000), (55.6, 12.0, 200000), (55.1, 14.9, 60000))
TJEK_PAGE = 100
TJEK_MAX_PAGES = 3
REMA_PER_PAGE = 1000
REMA_MAX_PAGES = 10
BLOCK_STATUSES = (401, 403, 429)


class SourceError(Exception):
    def __init__(self, message, blocked=False):
        super().__init__(message)
        self.blocked = blocked


class HttpTransport:
    """Live GETs with an identifying User-Agent and a pause between requests to one source."""

    def __init__(self, pause=1.0, timeout=60):
        self.pause = pause
        self.timeout = timeout
        self.counts = {}
        # nemlig.com hands a guest cookie to GetBasket and expects it back.
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def get_json(self, source, url, fixture):
        if self.counts.get(source):
            time.sleep(self.pause)
        self.counts[source] = self.counts.get(source, 0) + 1
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                   "Accept": "application/json"})
        try:
            with self.opener.open(req, timeout=self.timeout) as resp:
                body = resp.read()
                final = resp.geturl()
        except urllib.error.HTTPError as e:
            raise SourceError("HTTP %d for %s" % (e.code, url), blocked=e.code in BLOCK_STATUSES)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise SourceError("request failed for %s: %s" % (url, e))
        if (urllib.parse.urlsplit(final).netloc != urllib.parse.urlsplit(url).netloc
                or "queue-it" in final.lower()):
            raise SourceError("redirected from %s to %s (possible queue or block page)"
                              % (url, final), blocked=True)
        try:
            return json.loads(body)
        except ValueError:
            raise SourceError("non-JSON response for %s (possible block page): %r"
                              % (url, body[:120]), blocked=True)


class FixtureTransport:
    """Serves saved responses from a directory; the fixture name stands in for the URL."""

    def __init__(self, directory):
        self.directory = directory
        self.counts = {}

    def get_json(self, source, url, fixture):
        self.counts[source] = self.counts.get(source, 0) + 1
        path = os.path.join(self.directory, fixture)
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except OSError as e:
            raise SourceError("cannot read fixture %s: %s" % (path, e.strerror))
        except ValueError as e:
            raise SourceError("bad JSON in fixture %s: %s" % (path, e))


def fetch_tjek(transport):
    """Return (offers, errors). A block response stops all further Tjek requests."""
    offers, errors = [], []
    for query in TJEK_QUERIES:
        fixture = "tjek_%s.json" % query.replace(" ", "_")
        for lat, lng, radius in TJEK_CENTRES:
            for page in range(TJEK_MAX_PAGES):
                params = {"query": query, "r_lat": lat, "r_lng": lng, "r_radius": radius,
                          "limit": TJEK_PAGE, "offset": page * TJEK_PAGE}
                url = TJEK_URL + "?" + urllib.parse.urlencode(params)
                try:
                    rows = transport.get_json("tjek", url, fixture)
                except SourceError as e:
                    errors.append(("Tjek", str(e)))
                    if e.blocked:
                        return offers, errors
                    break
                if not isinstance(rows, list):
                    errors.append(("Tjek", "unexpected response shape for %s" % url))
                    break
                offers.extend(rows)
                if len(rows) < TJEK_PAGE:
                    break
            else:
                errors.append(("Tjek", "stopped after %d pages for query %r; results may be cut"
                               % (TJEK_MAX_PAGES, query)))
    return offers, errors


def fetch_rema(transport):
    """Return (products, errors) from REMA's whole-catalogue paging."""
    products, errors = [], []
    page, last = 1, 1
    while page <= last:
        if page > REMA_MAX_PAGES:
            errors.append(("REMA", "catalogue has more than %d pages; stopped" % REMA_MAX_PAGES))
            break
        url = REMA_URL + "?" + urllib.parse.urlencode({"per_page": REMA_PER_PAGE, "page": page})
        try:
            body = transport.get_json("rema", url, "rema_page_%d.json" % page)
            products.extend(body["data"])
            last = int(body["meta"]["pagination"]["last_page"])
        except SourceError as e:
            errors.append(("REMA", str(e)))
            break
        except (KeyError, TypeError, ValueError) as e:
            errors.append(("REMA", "unexpected response shape on page %d: %r" % (page, e)))
            break
        page += 1
    return products, errors


def fetch_nemlig(transport, product_ids):
    """Return (products, errors) from nemlig's guest JSON chain for a fixed list of ids.

    Settings give ProductsImportedTimestamp, the guest basket gives TimeslotUtc and
    DeliveryZoneId, and each product is then read by id. A block stops the source.
    """
    products, errors = [], []
    if not product_ids:
        return products, errors
    if len(product_ids) > NEMLIG_MAX_IDS:
        raise ValueError("%d nemlig ids, more than the cap of %d; nothing was requested"
                         % (len(product_ids), NEMLIG_MAX_IDS))
    try:
        settings = transport.get_json("nemlig", NEMLIG_BASE + "/webapi/v2/AppSettings/Website",
                                      "nemlig_settings.json")
        basket = transport.get_json("nemlig", NEMLIG_BASE + "/webapi/basket/GetBasket",
                                    "nemlig_basket.json")
        path = "/webapi/%s/%s/%s/0/Products/Get" % tuple(
            urllib.parse.quote(str(v), safe="") for v in (
                settings["ProductsImportedTimestamp"], basket["TimeslotUtc"],
                basket["DeliveryZoneId"]))
    except SourceError as e:
        return products, [("nemlig", str(e))]
    except (KeyError, TypeError) as e:
        return products, [("nemlig", "unexpected settings or basket shape: %r" % (e,))]
    for pid in product_ids:
        url = NEMLIG_BASE + path + "?" + urllib.parse.urlencode({"id": pid})
        try:
            body = transport.get_json("nemlig", url, "nemlig_product_%s.json" % pid)
        except SourceError as e:
            errors.append(("nemlig", str(e)))
            if e.blocked:
                break
            continue
        if not isinstance(body, dict):
            errors.append(("nemlig", "unexpected product shape for id %s" % pid))
            continue
        products.append(body)
    return products, errors
