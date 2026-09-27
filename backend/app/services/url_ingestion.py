"""Phase 58, Part 2B: website-URL ingestion (Chatbase-parity feature). Fetches a real
page, strips nav/footer/script/style boilerplate, and returns clean title+text for the
existing KnowledgeDocument pipeline (app.services.knowledge_service.create_document) --
same chunking/embedding/draft-approval lifecycle as manual entry or file upload, not a
parallel system.

SSRF note: this endpoint accepts an arbitrary tenant-supplied URL and fetches it from
the server -- a classic SSRF vector (e.g. a tenant pointing it at a cloud metadata
endpoint or an internal service). `_validate_public_url` resolves the hostname and
refuses any private/loopback/link-local/reserved/multicast address, checked again on
every redirect hop (`_SSRFSafeRedirectHandler`), not just the URL the tenant typed.
"""
import ipaddress
import logging
import socket
import urllib.error
import urllib.parse
import urllib.request
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup

from app.core.exceptions import UnprocessableEntityError

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 10
_MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # 5MB -- a real page's HTML, generously capped
_USER_AGENT = "NightGuardAI-KnowledgeIngest/1.0 (+https://nightguard.ai/bot)"
# Elements whose text is boilerplate (site chrome), never the article/FAQ content
# itself, regardless of which vertical/tenant the page belongs to.
_BOILERPLATE_TAGS = ("script", "style", "nav", "header", "footer", "aside", "noscript", "form", "iframe", "svg")
_MAX_CRAWL_PAGES = 8


class URLFetchError(UnprocessableEntityError):
    """A real, user-facing reason the URL couldn't be ingested (unreachable, not
    public, not HTML, empty after stripping, etc.) -- distinct from a generic 422 so
    the dashboard can show the actual reason."""


def _validate_public_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise URLFetchError("Only http:// and https:// URLs are supported.")
    hostname = parsed.hostname
    if not hostname:
        raise URLFetchError("That doesn't look like a valid URL.")
    try:
        addrs = {info[4][0] for info in socket.getaddrinfo(hostname, None)}
    except socket.gaierror as exc:
        raise URLFetchError(f"Could not resolve host {hostname!r}.") from exc
    for addr in addrs:
        ip = ipaddress.ip_address(addr)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            raise URLFetchError("Refusing to fetch a non-public / internal address.")


class _SSRFSafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102 (stdlib override)
        _validate_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _fetch_raw_html(url: str) -> str:
    _validate_public_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    opener = urllib.request.build_opener(_SSRFSafeRedirectHandler)
    try:
        with opener.open(request, timeout=_TIMEOUT_SECONDS) as response:
            content_type = response.headers.get("Content-Type", "")
            if "html" not in content_type.lower():
                raise URLFetchError(f"That URL returned {content_type or 'a non-HTML response'}, not a web page.")
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise URLFetchError(f"The page returned HTTP {exc.code}.") from exc
    except urllib.error.URLError as exc:
        raise URLFetchError(f"Could not reach that URL: {exc.reason}.") from exc
    except TimeoutError as exc:
        raise URLFetchError("Timed out fetching that URL.") from exc
    if len(raw) > _MAX_RESPONSE_BYTES:
        raise URLFetchError(f"That page is larger than the {_MAX_RESPONSE_BYTES // (1024 * 1024)}MB fetch limit.")
    return raw.decode("utf-8", errors="replace")


def extract_title_and_text(html: str) -> tuple[str, str]:
    """Strips nav/footer/script/style boilerplate, returns (title, clean_text)."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(_BOILERPLATE_TAGS):
        tag.decompose()
    title_tag = soup.find("title")
    h1_tag = soup.find("h1")
    title = (title_tag.get_text(strip=True) if title_tag else "") or (h1_tag.get_text(strip=True) if h1_tag else "") or "Untitled page"
    main = soup.find("main") or soup.find("article") or soup.body or soup
    lines = [line.strip() for line in main.get_text(separator="\n").splitlines()]
    text = "\n".join(line for line in lines if line)
    return title, text


def fetch_and_extract(url: str) -> tuple[str, str]:
    """Fetches `url` and returns (title, clean_text). Raises URLFetchError on any
    real problem (unreachable, non-public, not HTML, nothing left after stripping)."""
    html = _fetch_raw_html(url)
    title, text = extract_title_and_text(html)
    if not text.strip():
        raise URLFetchError("No extractable text was found on that page after removing boilerplate.")
    return title, text


def _same_domain_links(base_url: str, html: str) -> list[str]:
    base = urllib.parse.urlparse(base_url)
    soup = BeautifulSoup(html, "html.parser")
    seen: list[str] = []
    for a in soup.find_all("a", href=True):
        joined = urllib.parse.urljoin(base_url, a["href"])
        parsed = urllib.parse.urlparse(joined)
        if parsed.scheme not in ("http", "https") or parsed.netloc != base.netloc:
            continue
        clean = parsed._replace(fragment="").geturl()
        if clean != base_url and clean not in seen:
            seen.append(clean)
    return seen


def _robots_allows(base_url: str, path_url: str) -> bool:
    parsed = urllib.parse.urlparse(base_url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    parser = RobotFileParser()
    parser.set_url(robots_url)
    try:
        parser.read()
    except (urllib.error.URLError, OSError):
        return True  # no reachable robots.txt -- default to allowed, same as any normal crawler would
    return parser.can_fetch(_USER_AGENT, path_url)


def crawl_site(seed_url: str, *, max_pages: int = _MAX_CRAWL_PAGES) -> list[tuple[str, str, str]]:
    """Shallow, same-domain, robots.txt-respecting crawl starting at `seed_url`: the
    seed page plus links found ON it (depth 1), capped at `max_pages` total. Returns a
    list of (url, title, clean_text) -- the seed page first, skipping any page that
    fails to fetch/extract rather than aborting the whole crawl. Not a general
    spider: no recursion past depth 1, no external links, by design (Part 2B scope)."""
    max_pages = min(max_pages, _MAX_CRAWL_PAGES)
    if not _robots_allows(seed_url, seed_url):
        raise URLFetchError("robots.txt on that site disallows fetching this URL.")
    seed_html = _fetch_raw_html(seed_url)
    seed_title, seed_text = extract_title_and_text(seed_html)
    pages: list[tuple[str, str, str]] = []
    if seed_text.strip():
        pages.append((seed_url, seed_title, seed_text))

    for link in _same_domain_links(seed_url, seed_html):
        if len(pages) >= max_pages:
            break
        if not _robots_allows(seed_url, link):
            continue
        try:
            title, text = fetch_and_extract(link)
        except URLFetchError as exc:
            logger.info("crawl_site: skipping %s (%s)", link, exc)
            continue
        pages.append((link, title, text))

    if not pages:
        raise URLFetchError("No extractable page content was found at that URL or its linked pages.")
    return pages
