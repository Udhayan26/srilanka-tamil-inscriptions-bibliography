"""Weekly collector for the Sri Lankan Tamil inscriptions bibliography.

Searches several sources with the Tamil and English keywords in config.json and
appends new, relevant items to data/raw/auto_<source>.tsv. Items already present
in any data/raw/*.tsv (same URL) are skipped, so it is safe to run repeatedly.

Sources:
  - Google News RSS (Tamil + English)      -> Newspaper Articles
  - Bing web search (RSS)                  -> Web Articles
  - Wikipedia (Tamil + English)            -> Web Articles
  - Ezhuna (WordPress REST API)            -> Magazines/Journals
  - Noolaham digital library (MediaWiki)   -> Books / Magazines / Newspapers
  - OpenAlex (scholarly works)             -> Research Papers / Books
  - Crossref (scholarly works)             -> Research Papers / Books

Every auto-collected row is marked "Auto-collected ... review" in Notes.
Run:  python scraper/collect.py [--only news,web,wikipedia,ezhuna,noolaham,openalex,crossref] [--backfill]
      Daily runs cover the last week; --backfill searches each year from 1996 to today.
"""
import argparse
import csv
import html
import json
import os
import re
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import date, datetime
from email.utils import parsedate_to_datetime

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")
CFG = json.load(open(os.path.join(ROOT, "scraper", "config.json"), encoding="utf-8"))
FIELDS = ["category", "type", "year", "date", "title", "author", "publisher_source", "language",
          "keywords", "url", "notes"]
UA = {"User-Agent": "SL-Tamil-Inscriptions-Bibliography/1.0 (research bibliography; github.com/Udhayan26)"}
TODAY = date.today().isoformat()
TAMIL_RE = re.compile(r"[஀-௿]")
BACKFILL = False  # set by --backfill: search every year since from_year instead of the last week
STATS = {}   # raw counts per source, written to data/last_run.json
ERRORS = []  # http problems, written to data/last_run.json for diagnosis


# ----------------------------------------------------------------- helpers
BROWSER_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                            "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
              "Accept": "application/json,text/html;q=0.9,*/*;q=0.8"}


def get(url, browser=False, **kw):
    for attempt in range(3):
        try:
            r = requests.get(url, headers=BROWSER_UA if browser else UA, timeout=30, **kw)
            if r.status_code == 200:
                return r
            if r.status_code in (429, 503):
                time.sleep(5 * (attempt + 1))
                continue
            print(f"  ! {r.status_code} {url[:120]}", file=sys.stderr)
            ERRORS.append(f"{r.status_code} {url[:160]}")
            return None
        except requests.RequestException as e:
            print(f"  ! {e.__class__.__name__} {url[:120]}", file=sys.stderr)
            ERRORS.append(f"{e.__class__.__name__} {url[:160]}")
            time.sleep(3)
    return None


def clean(s):
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return re.sub(r"\s+", " ", s).strip()


def lang_of(text):
    return "Tamil" if TAMIL_RE.search(text or "") else "English"


def has_any(text, words):
    t = (text or "").lower()
    return any(w.lower() in t for w in words)


def topic_hits(text):
    words = CFG["topic_keywords_ta"] + CFG["topic_keywords_en"]
    t = (text or "").lower()
    return [w for w in words if w.lower() in t]


def relevant(text, need_place=True):
    if not topic_hits(text):
        return False
    return has_any(text, CFG["place_keywords"]) if need_place else True


def paper_relevant(title, abstract):
    """Scholarly works: topic word in the title and Sri Lanka in title/abstract,
    or Sri Lanka in the title and at least two topic words in the abstract."""
    if has_any(title, CFG.get("exclude_keywords_papers", [])):
        return False
    t_topic, t_place = bool(topic_hits(title)), has_any(title, CFG["place_keywords"])
    if t_topic and (t_place or has_any(abstract, CFG["place_keywords"])):
        return True
    return t_place and len(set(topic_hits(abstract))) >= 2


def year_ok(y):
    return not y or (y.isdigit() and int(y) >= CFG["from_year"])


def existing_urls():
    seen = set()
    for name in os.listdir(RAW):
        if name.endswith(".tsv"):
            with open(os.path.join(RAW, name), encoding="utf-8") as f:
                for r in csv.DictReader(f, delimiter="\t"):
                    if r.get("url"):
                        seen.add(norm_url(r["url"]))
    return seen


def norm_url(u):
    u = u.strip().replace("http://", "https://").replace("://www.", "://")
    return u.rstrip("/").lower()


def append(source, rows, seen):
    path = os.path.join(RAW, f"auto_{source}.tsv")
    new = []
    for r in rows:
        key = norm_url(r["url"])
        if not r["url"] or key in seen or not year_ok(r["year"]):
            continue
        seen.add(key)
        r.setdefault("keywords", "; ".join(dict.fromkeys(topic_hits(r["title"] + " " + r.get("keywords", ""))))
                     or "")
        r["notes"] = (r.get("notes", "") + f" Auto-collected {TODAY} ({source}); review.").strip()
        new.append({k: (r.get(k) or "").replace("\t", " ").replace("\n", " ") for k in FIELDS})
    if not new:
        return 0
    write_header = not os.path.exists(path)
    with open(path, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, delimiter="\t")
        if write_header:
            w.writeheader()
        w.writerows(new)
    return len(new)


# ----------------------------------------------------------------- sources
def time_windows():
    """Daily runs look at the last 7 days; a backfill walks every year since from_year."""
    if not BACKFILL:
        return [" when:7d"]
    return [f" after:{y}-01-01 before:{y + 1}-01-01" for y in range(CFG["from_year"], date.today().year + 1)]


def google_news():
    out = []
    jobs = [(q, w) for q in CFG["news_queries"] for w in time_windows()]
    for q, window in jobs:
        hl, ceid = ("ta", "LK:ta") if TAMIL_RE.search(q) else ("en-LK", "LK:en")
        url = ("https://news.google.com/rss/search?q=" + urllib.parse.quote(q + window)
               + f"&hl={hl}&gl=LK&ceid={ceid}")
        r = get(url)
        if not r:
            continue
        try:
            root = ET.fromstring(r.content)
        except ET.ParseError:
            continue
        for it in root.iter("item"):
            title = clean(it.findtext("title"))
            src = clean(it.findtext("source")) or ""
            if src and title.endswith(" - " + src):
                title = title[: -len(src) - 3]
            desc = clean(it.findtext("description"))
            sl_outlet = has_any(src, CFG.get("sri_lankan_outlets", []))
            if not (relevant(title + " " + desc, need_place=True) or (sl_outlet and relevant(title, need_place=False))):
                continue
            if has_any(title, CFG.get("exclude_keywords", [])):
                continue
            pub = it.findtext("pubDate")
            d = ""
            try:
                d = parsedate_to_datetime(pub).date().isoformat()
            except Exception:
                pass
            out.append({"category": "Newspaper Articles", "type": "News", "year": d[:4], "date": d,
                        "title": title, "author": "", "publisher_source": src, "language": lang_of(title),
                        "url": it.findtext("link") or "", "notes": f"Google News query: {q}."})
        time.sleep(1)
    return out


def ezhuna():
    out = []
    for q in CFG["ezhuna_queries"]:
        for page in range(1, 6):
            url = ("https://www.ezhunaonline.com/wp-json/wp/v2/posts?per_page=100&_embed=author&search="
                   + urllib.parse.quote(q) + f"&page={page}")
            r = get(url)
            if not r:
                break
            try:
                posts = r.json()
            except ValueError:
                break
            if not isinstance(posts, list) or not posts:
                break
            for p in posts:
                title = clean(p.get("title", {}).get("rendered"))
                excerpt = clean(p.get("excerpt", {}).get("rendered"))
                # topic word in the title, or at least two distinct topic words in the excerpt
                if not (topic_hits(title) or len(set(topic_hits(excerpt))) >= 2):
                    continue
                author = ""
                emb = p.get("_embedded", {}).get("author") or []
                if emb and isinstance(emb[0], dict):
                    author = emb[0].get("name", "")
                d = (p.get("date") or "")[:10]
                out.append({"category": "Magazines/Journals", "type": "Online magazine article",
                            "year": d[:4], "date": d, "title": title, "author": author,
                            "publisher_source": "Ezhuna (எழுநா)", "language": lang_of(title),
                            "url": p.get("link", ""), "notes": ""})
            if len(posts) < 100:
                break
            time.sleep(1)
    return out


NOOLAHAM_APIS = ["https://noolaham.org/wiki/api.php", "https://noolaham.org/w/api.php",
                 "https://www.noolaham.org/wiki/api.php"]
NOOLAHAM_API = NOOLAHAM_APIS[0]


def noolaham_api():
    """Return the first Noolaham API endpoint that answers with JSON."""
    for api in NOOLAHAM_APIS:
        r = get(api, browser=True, params={"action": "query", "meta": "siteinfo", "format": "json"})
        if r is not None:
            try:
                r.json()
                return api
            except ValueError:
                ERRORS.append(f"non-JSON reply from {api}: {r.text[:80]!r}")
    return None
NOOLAHAM_TYPES = {"நூல்": ("Books", "Book"), "இதழ்": ("Magazines/Journals", "Magazine/Journal issue"),
                  "பத்திரிகை": ("Newspaper Articles", "Newspaper issue"),
                  "சிறப்புமலர்": ("Magazines/Journals", "Special issue / souvenir"),
                  "நினைவுமலர்": ("Magazines/Journals", "Memorial volume"),
                  "அறிக்கை": ("Research Papers", "Report"), "பிரசுரம்": ("Books", "Pamphlet")}


def parse_template(wikitext):
    m = re.search(r"\{\{\s*([^|}\n]+?)\s*\|(.*?)\}\}", wikitext or "", re.S)
    if not m:
        return "", {}
    name = m.group(1).replace(" ", "")
    body = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", m.group(2))  # flatten [[link|label]] first
    fields = {}
    for part in body.split("|"):
        if "=" in part:
            k, v = part.split("=", 1)
            fields[k.strip()] = clean(v)
    return name, fields


def noolaham():
    out = []
    titles = set()
    api = noolaham_api()
    if not api:
        return out
    for q in CFG["noolaham_queries"]:
        for offset in range(0, 1000, 500):
            r = get(api, browser=True, params={"action": "query", "list": "search", "srsearch": q,
                                          "srlimit": 500, "sroffset": offset, "srnamespace": 0,
                                          "format": "json"})
            if not r:
                break
            try:
                hits = r.json().get("query", {}).get("search", [])
            except ValueError:
                break
            for h in hits:
                if relevant(h["title"] + " " + clean(h.get("snippet", "")), need_place=False):
                    titles.add(h["title"])
            if len(hits) < 500:
                break
            time.sleep(1)
    titles = sorted(titles)
    for i in range(0, len(titles), 40):
        batch = titles[i:i + 40]
        r = get(api, browser=True, params={"action": "query", "prop": "revisions", "rvprop": "content",
                                      "rvslots": "main", "titles": "|".join(batch), "format": "json"})
        if not r:
            continue
        try:
            pages = r.json().get("query", {}).get("pages", {})
        except ValueError:
            continue
        for p in pages.values():
            revs = p.get("revisions") or []
            if not revs:
                continue
            text = revs[0].get("slots", {}).get("main", {}).get("*") or revs[0].get("*", "")
            tname, f = parse_template(text)
            cat, typ = NOOLAHAM_TYPES.get(tname, ("Books", tname or "Document"))
            y = re.search(r"(1[89]\d\d|20\d\d)", f.get("வெளியீட்டாண்டு", "") or f.get("வெளியீடு", ""))
            year = y.group(1) if y else ""
            title = p["title"]
            if not relevant(title + " " + f.get("வகை", ""), need_place=False):
                continue
            out.append({"category": cat, "type": typ, "year": year, "date": "", "title": title,
                        "author": f.get("ஆசிரியர்", "") or f.get("இதழாசிரியர்", ""),
                        "publisher_source": f.get("வெளியீட்டாளர்", "") or "Noolaham",
                        "language": f.get("மொழி", "") or lang_of(title),
                        "url": "https://noolaham.org/wiki/index.php/" + urllib.parse.quote(title.replace(" ", "_")),
                        "notes": f"Noolaham No. {f.get('நூலக எண்', '')}; pages {f.get('பக்கங்கள்', '')}."})
        time.sleep(1)
    return out


def openalex():
    out = []
    for q in CFG["paper_queries"]:
        url = ("https://api.openalex.org/works?per-page=100&search=" + urllib.parse.quote(q)
               + f"&filter=publication_year:>{CFG['from_year'] - 1}")
        r = get(url)
        if not r:
            continue
        results = r.json().get("results", [])
        STATS.setdefault("openalex_raw", 0)
        STATS["openalex_raw"] += len(results)
        for w in results:
            title = clean(w.get("title") or "")
            abstract = " ".join((w.get("abstract_inverted_index") or {}).keys())
            if not title or not paper_relevant(title, abstract):
                continue
            authors = ", ".join(a["author"]["display_name"] for a in w.get("authorships", [])[:6])
            venue = ((w.get("primary_location") or {}).get("source") or {}).get("display_name") or ""
            wtype = w.get("type") or "article"
            cat = "Books" if wtype in ("book", "monograph") else "Research Papers"
            link = w.get("doi") or (w.get("primary_location") or {}).get("landing_page_url") or w.get("id")
            out.append({"category": cat, "type": wtype.replace("-", " ").capitalize(),
                        "year": str(w.get("publication_year") or ""), "date": w.get("publication_date") or "",
                        "title": title, "author": authors, "publisher_source": venue,
                        "language": "English" if (w.get("language") in (None, "en")) else w.get("language"),
                        "url": link, "notes": f"OpenAlex query: {q}."})
        time.sleep(1)
    return out


def crossref():
    out = []
    for q in CFG["paper_queries"]:
        r = get("https://api.crossref.org/works", params={"query.bibliographic": q, "rows": 60,
                                                          "filter": f"from-pub-date:{CFG['from_year']}"})
        if not r:
            continue
        for it in r.json().get("message", {}).get("items", []):
            title = clean((it.get("title") or [""])[0])
            abstract = clean(it.get("abstract", ""))
            if not title or not paper_relevant(title, abstract):
                continue
            parts = (it.get("issued") or {}).get("date-parts") or [[None]]
            y = str(parts[0][0] or "")
            d = "-".join(f"{x:02d}" if i else str(x) for i, x in enumerate(parts[0]) if x) if parts[0][0] else ""
            authors = ", ".join(f"{a.get('given', '')} {a.get('family', '')}".strip()
                                for a in it.get("author", [])[:6])
            typ = it.get("type", "journal-article")
            cat = "Books" if typ in ("book", "monograph", "edited-book") else "Research Papers"
            out.append({"category": cat, "type": typ.replace("-", " ").capitalize(), "year": y,
                        "date": d if len(d) == 10 else "", "title": title, "author": authors,
                        "publisher_source": (it.get("container-title") or [it.get("publisher", "")])[0],
                        "language": lang_of(title), "url": "https://doi.org/" + it["DOI"],
                        "notes": f"Crossref query: {q}."})
        time.sleep(1)
    return out


def bing_web():
    """General web pages (blogs, heritage sites, online articles) via Bing's RSS output."""
    out = []
    windows = [""] if not BACKFILL else [f" {y}" for y in range(CFG["from_year"], date.today().year + 1)]
    for q in CFG.get("web_queries", []):
        for w in windows:
            r = get("https://www.bing.com/search", browser=True,
                    params={"q": q + w, "format": "rss", "count": 50, "setlang": "en"})
            if not r:
                continue
            try:
                root = ET.fromstring(r.content)
            except ET.ParseError:
                ERRORS.append(f"bing non-RSS reply for {q + w!r}")
                continue
            items = list(root.iter("item"))
            STATS["bing_raw"] = STATS.get("bing_raw", 0) + len(items)
            for it in items:
                title = clean(it.findtext("title"))
                desc = clean(it.findtext("description"))
                link = it.findtext("link") or ""
                host = urllib.parse.urlparse(link).netloc.lower().replace("www.", "")
                if any(host.endswith(d) for d in CFG.get("web_skip_domains", [])):
                    continue
                if not relevant(title + " " + desc, need_place=True) or has_any(title, CFG.get("exclude_keywords", [])):
                    continue
                y = ""
                m = re.search(r"/(19[89]\d|20[0-3]\d)/", link) or re.search(r"\b(199[6-9]|20[0-3]\d)\b", desc[:40])
                if m:
                    y = m.group(1)
                d = ""
                try:
                    d = parsedate_to_datetime(it.findtext("pubDate")).date().isoformat()
                except Exception:
                    pass
                out.append({"category": "Web Articles", "type": "Web page", "year": y or d[:4], "date": d if not y else "",
                            "title": title, "author": "", "publisher_source": host, "language": lang_of(title),
                            "url": link, "notes": f"Web search: {q + w}."})
            time.sleep(2)
    return out


def ddg_web():
    """Fallback web search through DuckDuckGo's HTML endpoint."""
    out = []
    windows = [""] if not BACKFILL else [f" {y}" for y in range(CFG["from_year"], date.today().year + 1)]
    pat = re.compile(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?'
                     r'class="result__snippet"[^>]*>(.*?)</(?:a|div)>', re.S)
    for q in CFG.get("web_queries", []):
        for w in windows:
            try:
                r = requests.post("https://html.duckduckgo.com/html/", data={"q": q + w, "kl": "wt-wt"},
                                  headers=BROWSER_UA, timeout=30)
            except requests.RequestException as e:
                ERRORS.append(f"ddg {e.__class__.__name__}")
                continue
            if r.status_code != 200:
                ERRORS.append(f"ddg {r.status_code} {q + w}")
                time.sleep(10)
                continue
            hits = pat.findall(r.text)
            STATS["ddg_raw"] = STATS.get("ddg_raw", 0) + len(hits)
            for href, t, snip in hits:
                link = href
                if "uddg=" in href:
                    link = urllib.parse.unquote(urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get("uddg", [href])[0])
                title, desc = clean(t), clean(snip)
                host = urllib.parse.urlparse(link).netloc.lower().replace("www.", "")
                if not host or any(host.endswith(d) for d in CFG.get("web_skip_domains", [])):
                    continue
                if not relevant(title + " " + desc, need_place=True) or has_any(title, CFG.get("exclude_keywords", [])):
                    continue
                m = re.search(r"/(199[6-9]|20[0-3]\d)/", link)
                out.append({"category": "Web Articles", "type": "Web page", "year": m.group(1) if m else "",
                            "date": "", "title": title, "author": "", "publisher_source": host,
                            "language": lang_of(title), "url": link, "notes": f"Web search: {q + w}."})
            time.sleep(3)
    return out


def wikipedia():
    """Tamil and English Wikipedia articles on Sri Lankan Tamil inscriptions and archaeology."""
    out = []
    for lang, queries in (("ta", CFG.get("wiki_queries_ta", [])), ("en", CFG.get("wiki_queries_en", []))):
        api = f"https://{lang}.wikipedia.org/w/api.php"
        titles = set()
        for q in queries:
            r = get(api, params={"action": "query", "list": "search", "srsearch": q, "srlimit": 50, "format": "json"})
            if not r:
                continue
            for h in r.json().get("query", {}).get("search", []):
                t, snip = h["title"], clean(h.get("snippet", ""))
                if has_any(t, CFG.get("exclude_keywords", [])) or re.search(r"\d", t):
                    continue
                # inscription/archaeology word in the title, or a Sri Lankan place in the title
                # with at least two topic words in the snippet
                if (topic_hits(t) and has_any(t + " " + snip, CFG["place_keywords"])) or \
                        (has_any(t, CFG["place_keywords"]) and len(set(topic_hits(snip))) >= 2):
                    titles.add(t)
            time.sleep(1)
        for t in sorted(titles):
            r = get(api, params={"action": "query", "prop": "revisions", "titles": t, "rvlimit": 1,
                                 "rvdir": "newer", "rvprop": "timestamp", "format": "json"})
            created = ""
            if r:
                for pg in r.json().get("query", {}).get("pages", {}).values():
                    created = ((pg.get("revisions") or [{}])[0].get("timestamp") or "")[:10]
            out.append({"category": "Web Articles", "type": "Encyclopedia article", "year": created[:4],
                        "date": created, "title": t, "author": "Wikipedia contributors",
                        "publisher_source": f"Wikipedia ({lang})", "language": "Tamil" if lang == "ta" else "English",
                        "url": f"https://{lang}.wikipedia.org/wiki/" + urllib.parse.quote(t.replace(" ", "_")),
                        "notes": "Date = page creation."})
            time.sleep(0.5)
    return out


SOURCES = {"news": google_news, "web": bing_web, "ddg": ddg_web, "wikipedia": wikipedia, "ezhuna": ezhuna,
           "noolaham": noolaham, "openalex": openalex, "crossref": crossref}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="comma-separated subset of: " + ",".join(SOURCES))
    ap.add_argument("--backfill", action="store_true",
                    help="search year by year from from_year to today (slow; run once)")
    args = ap.parse_args()
    global BACKFILL
    BACKFILL = args.backfill
    chosen = [s for s in (args.only.split(",") if args.only else SOURCES) if s in SOURCES]
    seen = existing_urls()
    report = {}
    for name in chosen:
        print(f"[{datetime.now():%H:%M:%S}] {name} ...")
        try:
            rows = SOURCES[name]()
        except Exception as e:  # one failing source must not stop the others
            print(f"  ! {name} failed: {e}", file=sys.stderr)
            rows = []
        added = append(name, rows, seen)
        report[name] = {"found": len(rows), "added": added}
        print(f"  found {len(rows)}, added {added}")
    with open(os.path.join(ROOT, "data", "last_run.json"), "w", encoding="utf-8") as f:
        json.dump({"date": TODAY, "backfill": BACKFILL, "sources": report, "stats": STATS, "errors": ERRORS[:50]}, f,
                  ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
