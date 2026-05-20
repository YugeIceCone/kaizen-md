"""Stdlib-only BFS crawler — roadmap items S1 + S2 + S3.

Built for `kaizen-scrape crawl <start_url>`. No third-party deps:
urllib.request for fetching, html.parser for link extraction,
urllib.robotparser for robots.txt, xml.etree.ElementTree for sitemap.

## What's covered

S1 — crawl subcommand:
  - BFS link walk
  - --depth, --max-pages, --include-subdomains
  - --allow-pattern / --block-pattern regex filters
  - --rate-limit-ms between requests

S2 — robots.txt + sitemap.xml:
  - Honor robots.txt (--respect-robots, on by default)
  - Seed the queue with sitemap.xml URLs when available

S3 — resume / incremental:
  - scrape_urls(canonical_url PK, last_scraped, depth, discovered_from)
  - Skip URLs scraped within --max-age-days (default 7)

## What's deferred

Per roadmap: link-graph table (S4), HEAD pre-check (S5), canonical-URL
exhaustive normalization (S6, partial here), per-host async concurrency
(S7), sitemap export (S8). All independent of S1/S2/S3 — can land later.

## Testing

The `crawl()` function accepts an injectable `fetch_fn` so tests can
swap in a stub that returns canned (status, content_type, body) tuples
without hitting the network. Same for `robots_fn` and `sitemap_fn`.
"""
from __future__ import annotations

import datetime as dt
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Callable

DEFAULT_USER_AGENT = "kaizen-scrape/1.0 (+https://github.com/kaizen)"
DEFAULT_TIMEOUT = 10.0

# ─── URL helpers (S6 partial — canonicalization) ──────────────────────

def canonical_url(url: str, base: str | None = None) -> str:
    """Normalize: absolutize against base, strip fragment, lowercase host,
    ensure path starts with /. Idempotent on already-canonical URLs."""
    if base:
        url = urllib.parse.urljoin(base, url)
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"unsupported scheme: {parsed.scheme!r} in {url!r}")
    netloc = parsed.netloc.lower()
    path = parsed.path or "/"
    return urllib.parse.urlunparse(
        parsed._replace(netloc=netloc, path=path, fragment="")
    )

def same_origin(url1: str, url2: str, include_subdomains: bool = False) -> bool:
    h1 = urllib.parse.urlparse(url1).netloc.lower()
    h2 = urllib.parse.urlparse(url2).netloc.lower()
    if h1 == h2:
        return True
    if not include_subdomains:
        return False
    # Subdomain match: one host is a suffix of the other (after the leading dot).
    return h1.endswith("." + h2) or h2.endswith("." + h1)

# ─── HTML link extraction ──────────────────────────────────────────────

class LinkExtractor(HTMLParser):
    """Pull `href` from <a> tags. Other attrs are ignored. Robust against
    malformed HTML (HTMLParser is lenient by default)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        for name, value in attrs:
            if name.lower() == "href" and value:
                self.links.append(value)

def extract_links(html: str) -> list[str]:
    """Parse `html` and return the list of href values (raw, not canonicalized)."""
    ex = LinkExtractor()
    try:
        ex.feed(html)
    except Exception:
        # HTMLParser shouldn't raise but be defensive about exotic input
        pass
    return ex.links

# ─── Fetching (with injectable stub for tests) ────────────────────────

FetchResult = tuple[int, str, bytes]  # (status, content_type, body)
FetchFn = Callable[..., FetchResult]

def fetch_url(
    url: str,
    *,
    user_agent: str = DEFAULT_USER_AGENT,
    timeout: float = DEFAULT_TIMEOUT,
) -> FetchResult:
    """Stdlib GET; returns (status, content_type, body) or raises URLError."""
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.headers.get("Content-Type", ""), resp.read()

# ─── robots.txt + sitemap ─────────────────────────────────────────────

def load_robots(
    base_url: str,
    user_agent: str = DEFAULT_USER_AGENT,
) -> urllib.robotparser.RobotFileParser:
    """Fetch and parse /robots.txt for the URL's host. On any error
    returns an empty RobotParser (= allow-all)."""
    parsed = urllib.parse.urlparse(base_url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(robots_url)
    try:
        rp.read()
    except (OSError, urllib.error.URLError):
        pass
    return rp

def load_sitemap_urls(
    base_url: str,
    *,
    fetch_fn: FetchFn = fetch_url,
    user_agent: str = DEFAULT_USER_AGENT,
) -> list[str]:
    """Look for sitemap.xml / sitemap_index.xml at the base host. Returns
    a list of URLs found in the sitemap, or [] on absence/error."""
    parsed = urllib.parse.urlparse(base_url)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    for path in ("/sitemap.xml", "/sitemap_index.xml"):
        url = f"{parsed.scheme}://{parsed.netloc}{path}"
        try:
            status, _ctype, body = fetch_fn(url, user_agent=user_agent)
            if status != 200:
                continue
            tree = ET.fromstring(body)
            locs = [
                loc.text.strip()
                for loc in tree.findall(".//sm:loc", ns)
                if loc.text and loc.text.strip()
            ]
            if locs:
                return locs
        except (OSError, urllib.error.URLError, ET.ParseError, ValueError):
            continue
    return []

# ─── scrape_urls table (S3) ───────────────────────────────────────────

SCRAPE_URLS_DDL = """
CREATE TABLE IF NOT EXISTS scrape_urls (
    canonical_url TEXT PRIMARY KEY,
    last_scraped TEXT NOT NULL,
    depth INTEGER NOT NULL DEFAULT 0,
    discovered_from TEXT
);
CREATE INDEX IF NOT EXISTS idx_scrape_urls_ts ON scrape_urls(last_scraped);
"""

def ensure_scrape_urls_table(conn: sqlite3.Connection) -> None:
    """Idempotent — creates table + index if absent."""
    conn.executescript(SCRAPE_URLS_DDL)

def is_recently_scraped(
    conn: sqlite3.Connection, url: str, max_age_days: int
) -> bool:
    """True iff url is in scrape_urls with last_scraped within max_age_days."""
    cutoff = (
        dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=max_age_days)
    ).isoformat()
    row = conn.execute(
        "SELECT 1 FROM scrape_urls WHERE canonical_url = ? AND last_scraped > ?",
        (url, cutoff),
    ).fetchone()
    return row is not None

def record_url(
    conn: sqlite3.Connection,
    url: str,
    *,
    depth: int = 0,
    discovered_from: str | None = None,
) -> None:
    """Upsert. last_scraped is set to now (UTC, ISO-8601)."""
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO scrape_urls (canonical_url, last_scraped, depth, discovered_from)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(canonical_url) DO UPDATE SET
             last_scraped = excluded.last_scraped,
             depth = excluded.depth,
             discovered_from = excluded.discovered_from""",
        (url, now, depth, discovered_from),
    )

# ─── Crawl driver ─────────────────────────────────────────────────────

@dataclass
class CrawlConfig:
    start_url: str
    depth: int = 2
    max_pages: int = 100
    include_subdomains: bool = False
    rate_limit_ms: int = 500
    allow_pattern: str | None = None
    block_pattern: str | None = None
    max_age_days: int = 7
    respect_robots: bool = True
    user_agent: str = DEFAULT_USER_AGENT

@dataclass
class CrawlResult:
    crawled: list[tuple[str, int]] = field(default_factory=list)  # (url, depth)
    skipped_robots: int = 0
    skipped_origin: int = 0
    skipped_pattern: int = 0
    skipped_recent: int = 0
    fetch_errors: int = 0

def crawl(
    config: CrawlConfig,
    *,
    fetch_fn: FetchFn | None = None,
    conn: sqlite3.Connection | None = None,
    on_page: Callable[[str, bytes, int], None] | None = None,
    sleep_fn: Callable[[float], None] | None = None,
    seed_with_sitemap: bool = True,
) -> CrawlResult:
    """BFS crawl from `config.start_url`. Returns a CrawlResult.

    fetch_fn:  swap to stub-fetch for tests. Defaults to fetch_url.
    conn:      sqlite3 connection with scrape_urls table; if provided,
               recently-scraped URLs are skipped + new visits recorded.
    on_page:   callback fired per successful 200/html fetch — receives
               (canonical_url, body_bytes, depth). The scrape_index
               integration uses this to push pages into the existing
               PocketFlow scrape pipeline.
    sleep_fn:  for tests; replaces time.sleep so rate-limit doesn't slow
               the suite.
    """
    fetch = fetch_fn or fetch_url
    sleep = sleep_fn or time.sleep
    result = CrawlResult()
    visited: set[str] = set()
    queue: list[tuple[str, int, str | None]] = []  # (url, depth, discovered_from)

    try:
        seed = canonical_url(config.start_url)
    except ValueError:
        return result
    queue.append((seed, 0, None))

    # S2: seed with sitemap URLs (depth 0 — they're discovery aids, not nav).
    if seed_with_sitemap:
        try:
            sitemap = load_sitemap_urls(
                seed, fetch_fn=fetch, user_agent=config.user_agent
            )
        except Exception:
            sitemap = []
        for sm_url in sitemap:
            try:
                cn = canonical_url(sm_url)
            except ValueError:
                continue
            queue.append((cn, 0, "sitemap"))

    # S2: robots.txt
    rp: urllib.robotparser.RobotFileParser | None = None
    if config.respect_robots:
        try:
            rp = load_robots(seed, user_agent=config.user_agent)
        except Exception:
            rp = None

    allow_re = re.compile(config.allow_pattern) if config.allow_pattern else None
    block_re = re.compile(config.block_pattern) if config.block_pattern else None

    fetched_count = 0
    while queue and len(result.crawled) < config.max_pages:
        url, depth, parent = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)
        if depth > config.depth:
            continue

        # Origin check
        if not same_origin(url, seed, config.include_subdomains):
            result.skipped_origin += 1
            continue

        # Pattern filters
        if allow_re and not allow_re.search(url):
            result.skipped_pattern += 1
            continue
        if block_re and block_re.search(url):
            result.skipped_pattern += 1
            continue

        # robots
        if rp and not rp.can_fetch(config.user_agent, url):
            result.skipped_robots += 1
            continue

        # S3: skip recently-scraped
        if conn is not None and is_recently_scraped(conn, url, config.max_age_days):
            result.skipped_recent += 1
            continue

        # Rate-limit (skip on the very first fetch)
        if fetched_count > 0 and config.rate_limit_ms > 0:
            sleep(config.rate_limit_ms / 1000.0)

        try:
            status, ctype, body = fetch(url, user_agent=config.user_agent)
        except (OSError, urllib.error.URLError):
            result.fetch_errors += 1
            continue
        fetched_count += 1

        if status != 200:
            continue
        if "html" not in ctype.lower():
            continue

        result.crawled.append((url, depth))
        if conn is not None:
            record_url(conn, url, depth=depth, discovered_from=parent)
        if on_page is not None:
            try:
                on_page(url, body, depth)
            except Exception:
                # Don't let downstream errors halt the crawl
                pass

        # Extract links and queue children
        try:
            html = body.decode("utf-8", errors="replace")
        except (UnicodeDecodeError, AttributeError):
            continue
        for raw_link in extract_links(html):
            try:
                child = canonical_url(raw_link, base=url)
            except ValueError:
                continue
            if child in visited:
                continue
            queue.append((child, depth + 1, url))

    return result
