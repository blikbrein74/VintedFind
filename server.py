#!/usr/bin/env python3
"""VintedFind: watch Vinted searches and get alerted about new listings.

Vinted has no public API. Its catalog page is server-rendered (Next.js) and
embeds the result list as JSON, so we fetch the same public page a browser
would and read the items out of it. Standard library only (Python 3.9+).

Usage:
    python3 server.py            # dashboard on http://localhost:8765
    python3 server.py --lan      # also reachable from your phone on the same Wi-Fi
"""
import argparse
import gzip
import http.cookiejar
import json
import os
import random
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(os.environ.get("VINTEDFIND_DATA") or os.path.join(APP_DIR, "data"), "state.json")
INDEX_FILE = os.path.join(APP_DIR, "static", "index.html")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
MIN_INTERVAL = 30          # seconds; be polite to Vinted
MAX_BACKOFF = 15 * 60
MAX_SEEN = 3000            # ids remembered per search
MAX_FEED = 400             # hits kept in the dashboard feed
DROP_PARAMS = {"page", "time", "search_id", "search_by_image_uuid", "disabled_personalization"}
SITE = os.environ.get("VINTEDFIND_SITE", "vinted.nl")
LOOKUP_TTL = 6 * 3600

FLIGHT_RE = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)')
ITEMS_KEY = '"items":{"items":'
TREE_KEY = '"catalogTree":'

# Vinted's condition ("status") ids are fixed; its filter API only returns French labels.
CONDITIONS = [("6", "New with tags"), ("1", "New without tags"), ("2", "Very good"),
              ("3", "Good"), ("4", "Satisfactory")]
SIZE_GROUP_LABELS = {
    "WOMEN-LT": "Women's sizes", "SHOES": "Women's shoes", "BRAS_NEW": "Bras",
    "WOMEN-BELTS": "Belts", "WOMEN-SOCKS": "Socks",
    "MEN-DE": "Men's sizes", "MEN-PANTS": "Trousers (waist)", "MEN-SHIRT": "Shirts (collar)",
    "MEN-SUIT": "Suit jackets", "SHOES-MEN-FR": "Men's shoes", "MEN-BELTS": "Belts", "MEN-SOCKS": "Socks",
    "CHILDREN-BABY": "Kids & baby sizes", "SHOES-KIDS": "Kids' shoes", "AGE-BABY": "Age",
    "Kids-Hat-US": "Kids' hats", "KID-BELTS": "Belts", "KID-SOCKS": "Socks",
    "RINGS": "Rings", "ADULT-HATS": "Hats", "WATCHES": "Watches", "ADULT-GLOVES": "Gloves",
}
SIZE_LABELS = {"Taille unique": "One size", "Autre": "Other"}
# Vinted's colour ids are fixed too; the hex is only for the swatch in the form.
COLORS = [
    ("1", "Black", "#111111"), ("3", "Grey", "#9a9a9a"), ("12", "White", "#ffffff"), ("20", "Cream", "#f3ead3"),
    ("4", "Beige", "#d8c3a5"), ("21", "Apricot", "#f8c58c"), ("11", "Orange", "#f28c28"), ("22", "Coral", "#f88379"),
    ("7", "Red", "#d62828"), ("23", "Burgundy", "#7b1e2b"), ("5", "Pink", "#e83e8c"), ("24", "Rose", "#f4b6c2"),
    ("6", "Purple", "#7b3fa0"), ("25", "Lilac", "#c8a2c8"), ("26", "Light blue", "#9ecbf0"), ("9", "Blue", "#1f5fbf"),
    ("27", "Navy", "#1b2a4a"), ("17", "Turquoise", "#30c5c0"), ("30", "Mint", "#a8e6cf"), ("10", "Green", "#2e8b3d"),
    ("28", "Dark green", "#1e4d2b"), ("16", "Khaki", "#8a8452"), ("2", "Brown", "#6b4226"), ("29", "Mustard", "#d4a017"),
    ("8", "Yellow", "#f5d90a"), ("13", "Silver", "#c0c0c0"), ("14", "Gold", "#d4af37"),
    ("15", "Multicolour", "conic-gradient(red, yellow, lime, cyan, blue, magenta, red)"), ("32", "Clear", "transparent"),
]

lock = threading.RLock()
wake = threading.Event()


# --------------------------------------------------------------------------- state

def default_state():
    return {
        "settings": {
            "interval": 60,
            "ntfy_enabled": False,
            "ntfy_server": "https://ntfy.sh",
            "ntfy_topic": "vintedfind-" + secrets.token_hex(6),
            "skip_promoted": True,
        },
        "searches": [],
        "feed": [],
    }


def load_state():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, encoding="utf-8") as f:
            st = json.load(f)
        base = default_state()
        base["settings"].update(st.get("settings", {}))
        st["settings"] = base["settings"]
        st.setdefault("searches", [])
        st.setdefault("feed", [])
        return st
    return default_state()


def save_state():
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    tmp = DATA_FILE + ".tmp"
    with lock:
        data = json.dumps(STATE, ensure_ascii=False)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(data)
    os.replace(tmp, DATA_FILE)


STATE = None


# --------------------------------------------------------------------------- vinted

def normalize_url(raw):
    """Turn any pasted Vinted search link into a newest-first catalog URL."""
    raw = raw.strip()
    if not raw.startswith("http"):
        raw = "https://" + raw
    u = urllib.parse.urlsplit(raw)
    host = u.netloc.lower()
    if not re.match(r"^(www\.)?vinted\.[a-z.]+$", host):
        raise ValueError("That doesn't look like a Vinted link (e.g. https://www.vinted.nl/catalog?...)")
    if not host.startswith("www."):
        host = "www." + host
    q = [(k, v) for k, v in urllib.parse.parse_qsl(u.query, keep_blank_values=True)
         if k not in DROP_PARAMS and k != "order"]
    q.append(("order", "newest_first"))
    path = u.path or "/catalog"
    return urllib.parse.urlunsplit(("https", host, path, urllib.parse.urlencode(q), ""))


class Fetcher:
    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def get(self, url):
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip",
        })
        with self.opener.open(req, timeout=40) as r:
            body = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                body = gzip.decompress(body)
        return body.decode("utf-8", "replace")

    def get_json(self, url):
        """Call one of the JSON endpoints the Vinted website itself uses for its filter menus."""
        if not any(c.name == "access_token_web" for c in self.jar):
            self.get("https://www.%s/" % SITE)  # pick up visitor cookies first, like a browser
        req = urllib.request.Request(url, headers={
            "User-Agent": UA, "Accept": "application/json",
            "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
            "Origin": "https://www.%s" % SITE, "Referer": "https://www.%s/" % SITE,
        })
        with self.opener.open(req, timeout=20) as r:
            return json.load(r)


def flight_json(html, key):
    """Find `key` in the page's embedded Next.js data and decode the JSON value after it."""
    flight = "".join(json.loads(c) for c in FLIGHT_RE.findall(html))
    k = flight.find(key)
    if k < 0:
        return None
    return json.JSONDecoder().raw_decode(flight, k + len(key))[0]


def extract_items(html, base_url):
    raw_items = flight_json(html, ITEMS_KEY)
    if raw_items is None:
        raise RuntimeError("No item list found on the page (Vinted may have changed its layout)")
    origin = "{0.scheme}://{0.netloc}".format(urllib.parse.urlsplit(base_url))
    out = []
    for it in raw_items:
        p = it.get("productItem") or {}
        if not p.get("id"):
            continue
        box = p.get("itemBox") or {}
        price = p.get("price") or {}
        total = p.get("totalItemPrice") or {}
        out.append({
            "id": p["id"],
            "title": p.get("title") or "",
            "url": origin + (p.get("url") or "/items/%s" % p["id"]),
            "price": price.get("amount"),
            "total": total.get("amount"),
            "currency": price.get("currencyCode") or "EUR",
            "photo": p.get("thumbnailUrl"),
            "brand": box.get("firstLine") if box.get("firstLine") != "$undefined" else "",
            "details": box.get("secondLine") if box.get("secondLine") != "$undefined" else "",
            "promoted": bool(p.get("isPromoted")),
        })
    return out


# --------------------------------------------------------------------------- filter lookups

class Lookups:
    """Brand / size / category options for the search form, cached so the form stays quick."""

    def __init__(self):
        self.fetcher = Fetcher()
        self.cache = {}

    def cached(self, key, fn):
        hit = self.cache.get(key)
        if hit and time.time() - hit[0] < LOOKUP_TTL:
            return hit[1]
        val = fn()
        self.cache[key] = (time.time(), val)
        return val

    def filters_api(self, path, catalog_id, **extra):
        q = {"search_text": "", "currency": "EUR", "attribute_ids[catalog]": catalog_id or ""}
        q.update(extra)
        return self.fetcher.get_json("https://api.%s/svc-filters/filters%s?%s" % (SITE, path, urllib.parse.urlencode(q)))

    def categories(self):
        def load():
            tree = flight_json(self.fetcher.get("https://www.%s/catalog" % SITE), TREE_KEY) or []
            def simplify(nodes):
                return [{"id": n["id"], "title": n["title"], "children": simplify(n.get("catalogs") or [])} for n in nodes]
            return simplify(tree)
        return self.cached("categories", load)

    def brands(self, text, catalog_id=None):
        text = text.strip()
        if not text:
            return []
        d = self.cached(("brands", text.lower(), catalog_id), lambda: self.filters_api(
            "/search", catalog_id, filter_search_code="brand", filter_search_text=text))
        return [{"id": o["id"], "title": o["title"]} for o in d.get("options", [])][:20]

    def sizes(self, catalog_id):
        d = self.cached(("sizes", catalog_id), lambda: self.filters_api("/facets", catalog_id, filter_code="size"))
        groups = []
        for g in d.get("options", []):
            opts = [{"id": o["id"], "title": SIZE_LABELS.get(o["title"], o["title"])} for o in g.get("options", []) if o.get("id")]
            if opts:
                groups.append({"id": g["id"], "title": SIZE_GROUP_LABELS.get(g["id"], g.get("title", "")), "options": opts})
        return groups


LOOKUPS = Lookups()


def build_url(flt):
    """Turn the form's filters into a newest-first Vinted catalog URL."""
    q = []
    if flt.get("text"):
        q.append(("search_text", flt["text"].strip()))
    if flt.get("category"):
        q.append(("catalog[]", str(flt["category"]["id"])))
    for key, param in (("brands", "brand_ids[]"), ("sizes", "size_ids[]"), ("conditions", "status_ids[]"),
                       ("colors", "color_ids[]")):
        for x in flt.get(key) or []:
            q.append((param, str(x["id"])))
    for key in ("price_from", "price_to"):
        if flt.get(key) not in (None, ""):
            q.append((key, str(flt[key])))
    if flt.get("price_from") or flt.get("price_to"):
        q.append(("currency", "EUR"))
    q.append(("order", "newest_first"))
    return "https://www.%s/catalog?%s" % (SITE, urllib.parse.urlencode(q))


def auto_name(flt):
    parts = [", ".join(b["title"] for b in flt.get("brands") or [])]
    if flt.get("text"):
        parts.insert(0, flt["text"].strip())
    if flt.get("category"):
        parts.append(flt["category"]["title"])
    if flt.get("sizes"):
        parts.append(", ".join(s["title"] for s in flt["sizes"][:4]) + ("…" if len(flt["sizes"]) > 4 else ""))
    if flt.get("colors"):
        parts.append("/".join(c["title"] for c in flt["colors"][:3]) + ("…" if len(flt["colors"]) > 3 else ""))
    if flt.get("price_to"):
        parts.append("≤ €%s" % flt["price_to"])
    return " · ".join(p for p in parts if p)


def clean_filters(data):
    """Keep only well-formed filter fields from the browser."""
    def picks(key):
        return [{"id": str(x["id"]), "title": str(x.get("title", ""))} for x in data.get(key) or [] if x.get("id")]
    def price(key):
        v = str(data.get(key) or "").replace(",", ".").strip()
        if not v:
            return None
        try:
            float(v)
        except ValueError:
            raise ValueError("Price should be a number, like 25 or 25.50")
        return v
    cat = data.get("category")
    flt = {
        "text": str(data.get("text") or "").strip(),
        "category": {"id": str(cat["id"]), "title": str(cat.get("title", "")), "path": str(cat.get("path", ""))} if cat and cat.get("id") else None,
        "brands": picks("brands"), "sizes": picks("sizes"), "conditions": picks("conditions"), "colors": picks("colors"),
        "price_from": price("price_from"), "price_to": price("price_to"),
    }
    if not (flt["text"] or flt["category"] or flt["brands"]):
        raise ValueError("Pick at least a brand, a category or a keyword, otherwise you'd get all of Vinted.")
    return flt


# --------------------------------------------------------------------------- alerts

def money(item):
    sym = "€" if item["currency"] == "EUR" else item["currency"] + " "
    return "%s%s" % (sym, item["price"])


def send_ntfy(settings, title, message, click=None, image=None):
    payload = {"topic": settings["ntfy_topic"], "title": title, "message": message, "tags": ["shopping"]}
    if click:
        payload["click"] = click
        payload["actions"] = [{"action": "view", "label": "Open on Vinted", "url": click}]
    if image:
        payload["attach"] = image
    req = urllib.request.Request(
        settings["ntfy_server"].rstrip("/") + "/",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    urllib.request.urlopen(req, timeout=20).read()


def notify_hits(search, hits):
    s = STATE["settings"]
    if not (s["ntfy_enabled"] and s["ntfy_topic"]):
        return
    # Avoid a burst: individual pushes for a handful, a summary beyond that.
    try:
        for it in hits[:5]:
            send_ntfy(s, "%s · %s" % (money(it), search["name"]),
                      " · ".join(x for x in (it["title"], it["brand"], it["details"]) if x),
                      click=it["url"], image=it["photo"])
        if len(hits) > 5:
            send_ntfy(s, "%d more new in %s" % (len(hits) - 5, search["name"]),
                      "Open VintedFind or Vinted to see them all.", click=search["url"])
    except Exception as e:  # never let a push failure stop polling
        print("[ntfy] failed:", e)


# --------------------------------------------------------------------------- poller

def check_search(fetcher, search):
    items = extract_items(fetcher.get(search["url"]), search["url"])
    seen = set(search.get("seen", []))
    first_run = not search.get("primed")
    skip_promoted = STATE["settings"].get("skip_promoted", True)
    new = [it for it in items if it["id"] not in seen and not (skip_promoted and it["promoted"])]
    with lock:
        search["seen"] = ([it["id"] for it in items if it["id"] not in seen] + search.get("seen", []))[:MAX_SEEN]
        search["primed"] = True
        search["last_check"] = time.time()
        search["last_error"] = None
        search["last_count"] = len(items)
        search["fail_streak"] = 0
        if first_run:
            return []  # first look only learns what's already there
        now = time.time()
        for it in reversed(new):
            STATE["feed"].insert(0, dict(it, search_id=search["id"], search_name=search["name"], found_at=now))
        del STATE["feed"][MAX_FEED:]
        search["hits"] = search.get("hits", 0) + len(new)
    return new


def poller():
    fetcher = Fetcher()
    next_run = {}
    while True:
        with lock:
            searches = [s for s in STATE["searches"] if s.get("enabled", True)]
            interval = max(MIN_INTERVAL, int(STATE["settings"]["interval"]))
        now = time.time()
        due = [s for s in searches if next_run.get(s["id"], 0) <= now or s.get("force")]
        for s in due:
            s.pop("force", None)
            try:
                hits = check_search(fetcher, s)
                if hits:
                    print("[%s] %d new in %s" % (time.strftime("%H:%M:%S"), len(hits), s["name"]))
                    notify_hits(s, hits)
                delay = interval
            except Exception as e:
                with lock:
                    s["fail_streak"] = s.get("fail_streak", 0) + 1
                    s["last_error"] = "%s: %s" % (type(e).__name__, e)
                    s["last_check"] = time.time()
                if isinstance(e, urllib.error.HTTPError) and e.code in (403, 429):
                    fetcher = Fetcher()  # fresh cookies
                delay = min(MAX_BACKOFF, interval * (2 ** s["fail_streak"]))
                print("[%s] error in %s: %s (retry in %ds)" % (time.strftime("%H:%M:%S"), s["name"], s["last_error"], delay))
            next_run[s["id"]] = time.time() + delay * random.uniform(0.85, 1.15)
            save_state()
            time.sleep(random.uniform(2, 5))  # space out requests between searches
        wake.wait(5)
        wake.clear()


# --------------------------------------------------------------------------- http api

def public_state():
    with lock:
        return {
            "settings": STATE["settings"],
            "searches": [{k: v for k, v in s.items() if k != "seen"} for s in STATE["searches"]],
            "feed": STATE["feed"][:200],
            "now": time.time(),
        }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            with open(INDEX_FILE, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/state":
            self.send_json(public_state())
        elif self.path.startswith("/api/lookup/"):
            u = urllib.parse.urlsplit(self.path)
            q = dict(urllib.parse.parse_qsl(u.query))
            try:
                if u.path == "/api/lookup/categories":
                    return self.send_json(LOOKUPS.categories())
                if u.path == "/api/lookup/brands":
                    return self.send_json(LOOKUPS.brands(q.get("q", ""), q.get("catalog")))
                if u.path == "/api/lookup/sizes":
                    return self.send_json(LOOKUPS.sizes(q.get("catalog")))
                if u.path == "/api/lookup/conditions":
                    return self.send_json([{"id": i, "title": t} for i, t in CONDITIONS])
                if u.path == "/api/lookup/colors":
                    return self.send_json([{"id": i, "title": t, "swatch": h} for i, t, h in COLORS])
            except Exception as e:
                return self.send_json({"error": "Couldn't reach Vinted: %s" % e}, 502)
            self.send_json({"error": "not found"}, 404)
        else:
            self.send_json({"error": "not found"}, 404)

    @staticmethod
    def search_target(data):
        """A search comes from the filter form, or (advanced) a pasted Vinted link."""
        if data.get("filters"):
            flt = clean_filters(data["filters"])
            return flt, build_url(flt)
        return None, normalize_url(data.get("url", ""))

    def do_POST(self):
        try:
            data = self.read_json()
            path = self.path
            if path == "/api/searches":
                flt, url = self.search_target(data)
                name = (data.get("name") or "").strip() or (flt and auto_name(flt)) or "Search %d" % (len(STATE["searches"]) + 1)
                s = {"id": secrets.token_hex(4), "name": name, "url": url, "filters": flt, "enabled": True,
                     "created": time.time(), "hits": 0, "seen": [], "primed": False, "force": True}
                with lock:
                    STATE["searches"].append(s)
                save_state(); wake.set()
                return self.send_json({"ok": True, "id": s["id"]})
            m = re.match(r"^/api/searches/([0-9a-f]+)/update$", path)
            if m:
                flt, url = self.search_target(data)
                with lock:
                    s = next((x for x in STATE["searches"] if x["id"] == m.group(1)), None)
                    if not s:
                        return self.send_json({"error": "unknown search"}, 404)
                    name = (data.get("name") or "").strip()
                    if s.get("filters") and name == auto_name(s["filters"]):
                        name = ""  # still the generated name: regenerate it for the new filters
                    s["name"] = name or (flt and auto_name(flt)) or s["name"]
                    if url != s["url"]:
                        # New filters mean a new result set: re-learn it quietly instead of alerting on all of it.
                        s.update(url=url, seen=[], primed=False, last_error=None, fail_streak=0)
                    s["filters"] = flt
                    s["force"] = True
                save_state(); wake.set()
                return self.send_json({"ok": True})
            m = re.match(r"^/api/searches/([0-9a-f]+)/(toggle|delete|check|rename)$", path)
            if m:
                sid, action = m.groups()
                with lock:
                    s = next((x for x in STATE["searches"] if x["id"] == sid), None)
                    if not s:
                        return self.send_json({"error": "unknown search"}, 404)
                    if action == "toggle":
                        s["enabled"] = not s.get("enabled", True)
                    elif action == "delete":
                        STATE["searches"].remove(s)
                        STATE["feed"] = [f for f in STATE["feed"] if f.get("search_id") != sid]
                    elif action == "check":
                        s["force"] = True
                    elif action == "rename":
                        s["name"] = (data.get("name") or s["name"]).strip()
                save_state(); wake.set()
                return self.send_json({"ok": True})
            if path == "/api/settings":
                with lock:
                    st = STATE["settings"]
                    if "interval" in data:
                        st["interval"] = max(MIN_INTERVAL, int(data["interval"]))
                    for k in ("ntfy_enabled", "skip_promoted"):
                        if k in data:
                            st[k] = bool(data[k])
                    for k in ("ntfy_server", "ntfy_topic"):
                        if k in data and str(data[k]).strip():
                            st[k] = str(data[k]).strip()
                save_state()
                return self.send_json({"ok": True})
            if path == "/api/test-notification":
                send_ntfy(STATE["settings"], "VintedFind is connected",
                          "You'll get a push like this for every new listing.")
                return self.send_json({"ok": True})
            if path == "/api/feed/clear":
                with lock:
                    STATE["feed"] = []
                save_state()
                return self.send_json({"ok": True})
            self.send_json({"error": "not found"}, 404)
        except ValueError as e:
            self.send_json({"error": str(e)}, 400)
        except Exception as e:
            self.send_json({"error": "%s: %s" % (type(e).__name__, e)}, 500)


def main():
    global STATE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--lan", action="store_true", help="listen on all interfaces (phone on same Wi-Fi)")
    args = ap.parse_args()

    STATE = load_state()
    for s in STATE["searches"]:
        s["force"] = True
    save_state()
    threading.Thread(target=poller, daemon=True).start()

    host = "0.0.0.0" if args.lan else "127.0.0.1"
    srv = ThreadingHTTPServer((host, args.port), Handler)
    print("VintedFind running → http://localhost:%d  (Ctrl+C to stop)" % args.port)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
