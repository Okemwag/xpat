"""Evidence harvester (AI enhancement 2): news search → articles → candidate flood evidence for human review.

Searches the GDELT DOC 2.0 API (news in 65 languages, searchable in English, JSON output; blog.gdeltproject.org/gdelt-doc-2-0-api-debuts)
restricted to Kenyan outlets, fetches each new article, and sends its text through the existing extraction step
(``ai/extraction.extract``: verbatim-quote check, geocoding, contact details removed before the AI call). Every candidate is
unapproved: nothing changes hazard until a named reviewer approves it in the evidence library.

Deterministic safeguards:
- Only http(s) URLs on public addresses are fetched (no loopback, private or link-local hosts), with a size and time limit.
- Articles already in the library (same source URL) or seen twice in one harvest are skipped.
- An article that names many places from the county hotspot list is marked NOT independent of that list, so it cannot
  inflate the hotspot hit-rate check (the reviewer can still change the flag).
- Only the URL, the quote and the place are kept; the article text is discarded after extraction.
"""

import hashlib
import ipaddress
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from ..core.errors import ModelError

GDELT = "https://api.gdeltproject.org/api/v2/doc/doc"
USER_AGENT = "xpat-nairobi-flood-hackathon/0.3 (evidence harvester)"
MAX_BYTES = 2_000_000
TIMEOUT_S = 15
MIN_TEXT = 200
LIST_PHRASES = (
    "flood-prone areas identified",
    "hotspots identified",
    "list of flood-prone",
    "identified flood hotspots",
    "flood hotspot areas",
)


def search_url(query, timespan="1y", max_records=25):
    """GDELT DOC 2.0 article-list query, restricted to outlets in Kenya and English-language articles."""
    q = f"{query} sourcecountry:kenya sourcelang:english"
    return (
        GDELT
        + "?"
        + urllib.parse.urlencode(
            {
                "query": q,
                "mode": "artlist",
                "format": "json",
                "maxrecords": max_records,
                "timespan": timespan,
                "sort": "datedesc",
            }
        )
    )


def _public_host(url):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return False
    try:
        infos = socket.getaddrinfo(
            parts.hostname,
            parts.port or (443 if parts.scheme == "https" else 80),
            proto=socket.IPPROTO_TCP,
        )
    except OSError:
        return False
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        ):
            return False
    return True


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _public_host(newurl):
            raise urllib.error.URLError("redirect to a non-public address refused")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def http_fetch(url):
    """GET a public http(s) URL. Returns text (decoded leniently), or raises ModelError."""
    if not _public_host(url):
        raise ModelError(
            "fetch_refused",
            f"Only public http(s) addresses can be fetched: {url[:120]}",
        )
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.5",
        },
    )
    try:
        with opener.open(request, timeout=TIMEOUT_S) as response:
            data = response.read(MAX_BYTES + 1)
            charset = response.headers.get_content_charset() or "utf-8"
    except Exception as exc:
        raise ModelError(
            "fetch_failed", f"Could not fetch {url[:120]} ({type(exc).__name__})"
        ) from None
    return data[:MAX_BYTES].decode(charset, errors="replace")


def parse_search(text):
    """Article list from a GDELT artlist JSON response; malformed responses give an error, not silence."""
    try:
        payload = json.loads(text) if text.strip() else {}
    except ValueError:
        raise ModelError(
            "harvest_failed",
            "The news search returned something that is not JSON (often a rate limit); try again shortly",
        ) from None
    articles = payload.get("articles") or []
    out = []
    for a in articles:
        url = str(a.get("url") or "").strip()
        if url.startswith(("http://", "https://")):
            out.append(
                {
                    "url": url,
                    "title": " ".join(str(a.get("title") or "").split())[:300],
                    "seen": str(a.get("seendate") or ""),
                    "domain": str(a.get("domain") or ""),
                }
            )
    return out


class _Text(HTMLParser):
    SKIP = {
        "script",
        "style",
        "noscript",
        "nav",
        "footer",
        "header",
        "aside",
        "form",
        "svg",
        "figure",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.depth += 1
        elif tag in ("p", "br", "li", "h1", "h2", "h3", "div"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if not self.depth:
            self.parts.append(data)


def article_text(html, limit=30000):
    """Readable text of an article page: paragraphs only, scripts/navigation removed, capped at the extraction limit."""
    parser = _Text()
    parser.feed(html)
    parser.close()
    lines = [" ".join(line.split()) for line in "".join(parser.parts).split("\n")]
    # Keep sentence-like lines; menus and bylines are short.
    text = "\n".join(line for line in lines if len(line) >= 60)
    return text[:limit]


def depends_on_hotspot_list(text, hotspot_names, threshold):
    """True when the article reproduces the county hotspot list (many listed names, or list wording)."""
    lowered = text.lower()
    named = {
        n
        for n in hotspot_names
        if re.search(r"\b" + re.escape(n.lower()) + r"\b", lowered)
    }
    return len(named) >= threshold or any(p in lowered for p in LIST_PHRASES), sorted(
        named
    )


def _key(url):
    parts = urllib.parse.urlsplit(url.strip())
    return f"{parts.netloc.lower().removeprefix('www.')}{parts.path.rstrip('/')}"


def harvest(
    config,
    llm,
    gazetteer,
    hotspot_names,
    fetch=http_fetch,
    known_sources=(),
    allow_call=lambda: True,
    queries=None,
    max_articles=None,
):
    """Search, fetch and extract. Returns {'articles': [...], 'candidates': [...], 'searched': [...]}.

    ``allow_call`` is consulted before each AI extraction (the organisation's AI quota); it stops the harvest when False.
    Candidates carry ``independent_of_hotspot_list`` and ``source`` = the article URL.
    """
    from .extraction import extract

    h = config.evidence_harvest
    queries = list(queries or h["queries"])
    max_articles = max_articles or h["max_articles"]
    known = {
        _key(s) for s in known_sources if str(s).startswith(("http://", "https://"))
    }
    seen, titles, articles, candidates, searched = set(), set(), [], [], []
    done = lambda: sum(a["status"] == "extracted" for a in articles) >= max_articles
    for query in queries:
        if done():
            break
        url = search_url(query, h["timespan"])
        try:
            found = parse_search(fetch(url))
            searched.append({"query": query, "results": len(found)})
        except ModelError as exc:
            searched.append({"query": query, "results": 0, "error": str(exc)})
            continue
        for item in found:
            if done():
                break
            key = _key(item["url"])
            title = hashlib.sha256(item["title"].lower().encode()).hexdigest()
            if key in seen or (item["title"] and title in titles):
                continue
            seen.add(key)
            titles.add(title)
            record = {
                "url": item["url"],
                "title": item["title"],
                "seen": item["seen"],
                "domain": item["domain"],
            }
            if key in known:
                articles.append({**record, "status": "already in library"})
                continue
            try:
                text = article_text(fetch(item["url"]))
            except ModelError as exc:
                articles.append({**record, "status": "not fetched", "reason": str(exc)})
                continue
            if len(text) < MIN_TEXT:
                articles.append({**record, "status": "no article text"})
                continue
            if not allow_call():
                articles.append({**record, "status": "stopped: AI quota reached"})
                return {
                    "articles": articles,
                    "candidates": candidates,
                    "searched": searched,
                    "stopped": True,
                }
            try:
                result = extract(text, item["url"], llm, gazetteer)
            except ModelError as exc:
                articles.append(
                    {**record, "status": "extraction failed", "reason": str(exc)}
                )
                continue
            listed, names = depends_on_hotspot_list(
                text, hotspot_names, h["hotspot_list_threshold"]
            )
            for c in result["candidates"]:
                candidates.append(
                    {
                        **c,
                        "independent_of_hotspot_list": not listed,
                        "article_title": item["title"],
                        "list_names_found": len(names),
                    }
                )
            articles.append(
                {
                    **record,
                    "status": "extracted",
                    "candidates": len(result["candidates"]),
                    "dropped": len(result["dropped"]),
                    "reproduces_hotspot_list": listed,
                    "model": result.get("model"),
                }
            )
    return {
        "articles": articles,
        "candidates": candidates,
        "searched": searched,
        "stopped": False,
    }
