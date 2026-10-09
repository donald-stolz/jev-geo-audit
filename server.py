import gzip
import hashlib
import io
import ipaddress
import json
import os
import socket
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html.parser import HTMLParser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from urllib.robotparser import RobotFileParser

HOST, PORT = "127.0.0.1", 8000
API_URL = "https://openrouter.ai/api/alpha/decisions"
MODEL_ID = "typesafe/jev-1.13"
USER_AGENT = "NextWork-GEO-Audit/1.0"
MAX_ATTEMPTS = 3
MAX_PAGES = 600
MAX_SITEMAPS = 50
MAX_SITEMAP_BYTES = 2_000_000
MAX_HTML_BYTES = 1_000_000
MAX_TEXT_CHARS = 20_000
SITE_POLICIES = {}
FETCH_SLOTS = {}
FETCH_LOCK = threading.Lock()

QUESTIONS = {
    "readiness": {
        "type": "score",
        "instructions": "How ready is `page.content` to be quoted as a concise answer? Judge only the supplied text.",
        "criteria": [
            "Vague or promotional; no direct answer.",
            "A topic is present, but the answer is hard to isolate.",
            "A usable answer exists but lacks support or structure.",
            "A direct answer is supported and easy to extract.",
            "A self-contained answer has specific support, transparent sourcing, and clear structure."
        ]
    },
    "weakest_signal": {
        "type": "choice",
        "instructions": "Which single citability signal is weakest in `page.content`?",
        "criteria": {
            "answer_clarity": "The answer is indirect, buried, or ambiguous.",
            "evidence_specificity": "Claims lack concrete, checkable support.",
            "source_transparency": "The basis of important claims is unclear.",
            "extractable_structure": "The answer is difficult to quote by itself.",
            "none": "No meaningful weakness is present."
        }
    },
    "verifiable_support": {
        "type": "noul",
        "instructions": "Does `page.content` contain at least one concrete supporting detail a reviewer could verify?",
        "criteria": {
            "true": "A source, measurement, dated fact, example, or checkable detail supports the answer.",
            "false": "The text relies on broad or unsupported claims."
        }
    }
}


class ApiProblem(Exception):
    def __init__(self, status, message, details=None):
        super().__init__(message)
        self.status, self.message, self.details = status, message, details


class SafeRedirectHandler(HTTPRedirectHandler):
    """Reject redirects that leave the authorised public host."""

    def __init__(self, expected_host):
        super().__init__()
        self.expected_host = expected_host

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_public_url(newurl, self.expected_host)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class ReadableHTMLParser(HTMLParser):
    """Collect visible text plus readable metadata from server HTML."""

    SKIP_TAGS = {"style", "noscript", "svg", "template"}
    BREAK_TAGS = {"article", "br", "div", "footer", "h1", "h2", "h3", "h4", "header", "li", "main", "p", "section"}
    META_DESCRIPTION_KEYS = {"description", "og:description", "twitter:description"}
    JSON_TEXT_KEYS = {"articlebody", "description", "headline", "name", "text"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip_stack = []
        self.in_title = False
        self.in_json_ld = False
        self.current_json = []
        self.json_documents = []
        self.title_parts = []
        self.text_parts = []
        self.meta_parts = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attributes = {str(key).lower(): value for key, value in attrs if key and value is not None}
        if self.skip_stack:
            if tag == "script" or tag in self.SKIP_TAGS:
                self.skip_stack.append(tag)
            return
        if tag == "script":
            script_type = attributes.get("type", "").split(";", 1)[0].strip().lower()
            if script_type == "application/ld+json":
                self.in_json_ld = True
                self.current_json = []
            else:
                self.skip_stack.append(tag)
            return
        if tag in self.SKIP_TAGS:
            self.skip_stack.append(tag)
            return
        if tag == "meta":
            key = (attributes.get("name") or attributes.get("property") or "").strip().lower()
            content = attributes.get("content", "").strip()
            if key in self.META_DESCRIPTION_KEYS and content:
                self.meta_parts.append(content)
        elif tag == "title":
            self.in_title = True
        elif tag in self.BREAK_TAGS:
            self.text_parts.append("\n")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self.in_json_ld and tag == "script":
            self.json_documents.append("".join(self.current_json))
            self.current_json = []
            self.in_json_ld = False
            return
        if self.skip_stack:
            if tag == self.skip_stack[-1]:
                self.skip_stack.pop()
            return
        if tag == "title":
            self.in_title = False
        elif tag in self.BREAK_TAGS:
            self.text_parts.append("\n")

    def handle_data(self, data):
        if self.in_json_ld:
            self.current_json.append(data)
            return
        if self.skip_stack:
            return
        cleaned = " ".join(data.split())
        if not cleaned:
            return
        if self.in_title:
            self.title_parts.append(cleaned)
        self.text_parts.append(cleaned)

    def append_json_value(self, value, output):
        if isinstance(value, str):
            output.append(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    output.append(item)
                elif isinstance(item, (dict, list)):
                    self.collect_json_text(item, output)
        elif isinstance(value, dict):
            self.collect_json_text(value, output)

    def collect_json_text(self, value, output):
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key).lower() in self.JSON_TEXT_KEYS:
                    self.append_json_value(item, output)
                elif isinstance(item, (dict, list)):
                    self.collect_json_text(item, output)
        elif isinstance(value, list):
            for item in value:
                self.collect_json_text(item, output)

    def result(self):
        title = " ".join(self.title_parts).strip()
        pieces = [line for line in " ".join(self.text_parts).splitlines() if line.strip()]
        pieces.extend(self.meta_parts)
        for document in self.json_documents:
            try:
                structured = json.loads(document)
            except json.JSONDecodeError:
                continue
            self.collect_json_text(structured, pieces)
        lines = []
        seen = set()
        for piece in pieces:
            cleaned = " ".join(str(piece).split())
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                lines.append(cleaned)
        return title, "\n".join(lines)[:MAX_TEXT_CHARS]


def load_env(path=".env"):
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def canonical_host(host):
    host = (host or "").lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def validate_public_url(url, expected_host=None):
    parts = urlsplit(url.strip())
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ApiProblem(400, "Use a complete public HTTP or HTTPS URL.")
    if parts.username or parts.password:
        raise ApiProblem(400, "Credentials are not allowed in website URLs.")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError as error:
        raise ApiProblem(400, "The website URL contains an invalid port.") from error
    if port not in {80, 443}:
        raise ApiProblem(400, "Only standard public web ports 80 and 443 are allowed.")
    host = canonical_host(parts.hostname)
    if expected_host and host != canonical_host(expected_host):
        raise ApiProblem(400, "The website redirected outside the authorised host.")
    try:
        answers = socket.getaddrinfo(parts.hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as error:
        raise ApiProblem(400, "The website hostname could not be resolved.") from error
    for answer in answers:
        address = ipaddress.ip_address(answer[4][0].split("%")[0])
        if not address.is_global:
            raise ApiProblem(400, "Private, local, reserved, and link-local addresses are blocked.")
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", parts.query, ""))


def fetch_resource(url, expected_host, max_bytes, allowed_types=None):
    safe_url = validate_public_url(url, expected_host)
    opener = build_opener(ProxyHandler({}), SafeRedirectHandler(expected_host))
    request = Request(safe_url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xml,text/xml,text/plain;q=0.9,*/*;q=0.1"})
    try:
        with opener.open(request, timeout=20) as response:
            final_url = validate_public_url(response.geturl(), expected_host)
            content_type = response.headers.get_content_type().lower()
            if allowed_types and content_type not in allowed_types:
                raise ApiProblem(415, f"Unsupported response type: {content_type}.")
            data = response.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise ApiProblem(413, "The remote response exceeded the project safety limit.")
            charset = response.headers.get_content_charset() or "utf-8"
            return data, final_url, response.status, content_type, charset
    except HTTPError as error:
        raise ApiProblem(error.code, f"The website returned HTTP {error.code} for {safe_url}.") from error
    except URLError as error:
        raise ApiProblem(502, f"The website request failed: {error.reason}.") from error


def load_policy(website_url):
    value = website_url.strip()
    if "://" not in value:
        value = f"https://{value}"
    root_url = validate_public_url(value)
    parts = urlsplit(root_url)
    origin = f"{parts.scheme}://{parts.netloc}"
    host = canonical_host(parts.hostname)
    robots_url = f"{origin}/robots.txt"
    parser = RobotFileParser()
    parser.set_url(robots_url)
    try:
        raw, robots_url, _, _, charset = fetch_resource(robots_url, host, 512_000)
        parser.parse(raw.decode(charset, errors="replace").splitlines())
    except ApiProblem as error:
        if error.status != 404:
            raise ApiProblem(502, "The crawler could not safely read robots.txt.") from error
        parser.parse([])
    delay = parser.crawl_delay(USER_AGENT) or parser.crawl_delay("*") or 0.5
    delay = max(0.5, min(float(delay), 10.0))
    policy = {"host": host, "origin": origin, "robotsUrl": robots_url, "parser": parser, "delay": delay}
    SITE_POLICIES[host] = policy
    return root_url, policy


def read_gzip_limited(data, limit):
    with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
        expanded = stream.read(limit + 1)
    if len(expanded) > limit:
        raise ApiProblem(413, "The expanded sitemap exceeded the project safety limit.")
    return expanded


def element_name(element):
    return element.tag.rsplit("}", 1)[-1].lower()


def child_locations(root):
    return [child.text.strip() for child in root.iter() if element_name(child) == "loc" and child.text and child.text.strip()]


def page_label(url):
    path = unquote(urlsplit(url).path).strip("/")
    leaf = path.rsplit("/", 1)[-1] if path else "Homepage"
    return leaf.replace("-", " ").replace("_", " ").strip().title() or "Homepage"


def page_id(url):
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def discover_pages(root_url, policy):
    parser = policy["parser"]
    sitemap_queue = parser.site_maps() or [f"{policy['origin']}/sitemap.xml"]
    sitemap_queue = [validate_public_url(url, policy["host"]) for url in sitemap_queue]
    seen_sitemaps = set()
    seen_pages = set()
    pages = []
    used_sitemaps = []
    sitemap_errors = 0

    while sitemap_queue and len(seen_sitemaps) < MAX_SITEMAPS and len(pages) < MAX_PAGES:
        sitemap_url = sitemap_queue.pop(0)
        if sitemap_url in seen_sitemaps:
            continue
        seen_sitemaps.add(sitemap_url)
        try:
            raw, final_url, _, _, _ = fetch_resource(sitemap_url, policy["host"], MAX_SITEMAP_BYTES)
            if final_url.endswith(".gz") or raw.startswith(b"\x1f\x8b"):
                raw = read_gzip_limited(raw, MAX_SITEMAP_BYTES)
            # Some valid sitemap responses place whitespace before the XML declaration.
            root = ET.fromstring(raw.lstrip())
        except (ApiProblem, ET.ParseError):
            sitemap_errors += 1
            continue
        used_sitemaps.append(final_url)
        locations = child_locations(root)
        if element_name(root) == "sitemapindex":
            for location in locations:
                if len(seen_sitemaps) + len(sitemap_queue) >= MAX_SITEMAPS:
                    break
                try:
                    sitemap_queue.append(validate_public_url(location, policy["host"]))
                except ApiProblem:
                    continue
            continue
        if element_name(root) != "urlset":
            continue
        for location in locations:
            if len(pages) >= MAX_PAGES:
                break
            try:
                page_url = validate_public_url(location, policy["host"])
            except ApiProblem:
                continue
            if page_url in seen_pages or not parser.can_fetch(USER_AGENT, page_url):
                continue
            seen_pages.add(page_url)
            pages.append({"id": page_id(page_url), "title": page_label(page_url), "url": page_url})

    if not pages and parser.can_fetch(USER_AGENT, root_url):
        pages.append({"id": page_id(root_url), "title": page_label(root_url), "url": root_url})
        notice = "No readable sitemap was found, so the audit contains the authorised homepage only."
    elif not pages:
        raise ApiProblem(403, "robots.txt does not permit this crawler to fetch the supplied website.")
    else:
        notice = f"Discovered {len(pages)} permitted public pages from {len(used_sitemaps)} sitemap file(s)."
        if sitemap_errors:
            notice += f" Skipped {sitemap_errors} unreadable sitemap file(s)."
    return pages, used_sitemaps, notice


def wait_for_fetch_slot(policy):
    host = policy["host"]
    with FETCH_LOCK:
        now = time.monotonic()
        reserved = max(now, FETCH_SLOTS.get(host, now))
        FETCH_SLOTS[host] = reserved + policy["delay"]
    wait = reserved - now
    if wait > 0:
        time.sleep(wait)


def extract_page(page, policy):
    if not policy["parser"].can_fetch(USER_AGENT, page["url"]):
        raise ApiProblem(403, "robots.txt does not permit this page to be fetched.")
    wait_for_fetch_slot(policy)
    raw, final_url, status, _, charset = fetch_resource(
        page["url"], policy["host"], MAX_HTML_BYTES, {"text/html", "application/xhtml+xml"}
    )
    parser = ReadableHTMLParser()
    parser.feed(raw.decode(charset, errors="replace"))
    title, content = parser.result()
    if len(content) < 80:
        raise ApiProblem(
            422,
            f"{final_url} exposed only {len(content)} extracted characters. At least 80 are required for an audit.",
            {"reason": "thin_content", "url": final_url, "extractedChars": len(content)}
        )
    return {
        "id": page["id"],
        "title": title or page["title"],
        "url": final_url,
        "content": content,
        "fetchedAt": utc_now(),
        "httpStatus": status,
        "source": "live_html"
    }


def decode_json(raw):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"error": {"message": raw or "Unreadable API response"}}


def retry_delay(headers, attempt):
    value = headers.get("Retry-After") if headers else None
    try:
        return min(float(value), 10) if value and float(value) > 0 else min(2 ** attempt, 4)
    except ValueError:
        return min(2 ** attempt, 4)


def call_jev(page):
    key = os.getenv("OPENROUTER_API_KEY")
    if not key or key == "your-api-key-here":
        raise ApiProblem(500, "Add OPENROUTER_API_KEY to .env before starting the server.")
    data = json.dumps({"model": MODEL_ID, "state": {"page": page}, "questions": QUESTIONS}).encode("utf-8")
    request = Request(API_URL, data=data, headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json"
    }, method="POST")
    for attempt in range(MAX_ATTEMPTS):
        try:
            with build_opener(ProxyHandler({})).open(request, timeout=60) as response:
                body = decode_json(response.read().decode("utf-8"))
                if body.get("error"):
                    raise ApiProblem(502, body["error"].get("message", "OpenRouter returned an error."), body)
                return body
        except HTTPError as error:
            body = decode_json(error.read().decode("utf-8", errors="replace"))
            source = body.get("error", {}).get("metadata", {}).get("limit_source")
            transient = error.code == 429 or error.code >= 500 or (error.code == 402 and source == "openrouter_in_flight_budget")
            if transient and attempt < MAX_ATTEMPTS - 1:
                time.sleep(retry_delay(error.headers, attempt))
                continue
            raise ApiProblem(error.code, body.get("error", {}).get("message", str(error)), body) from error
        except URLError as error:
            if attempt < MAX_ATTEMPTS - 1:
                time.sleep(2 ** attempt)
                continue
            raise ApiProblem(502, f"Network error: {error.reason}") from error
    raise ApiProblem(502, "The Jev request did not complete.")


def normalize(page, raw, elapsed):
    answers, usage = raw.get("answers", {}), raw.get("usage", {})
    ready = answers.get("readiness", {})
    weak = answers.get("weakest_signal", {})
    support = answers.get("verifiable_support", {})
    checks = [
        ready.get("type") == "score" and isinstance(ready.get("score"), (int, float)),
        weak.get("type") == "choice" and isinstance(weak.get("choice"), str),
        support.get("type") == "noul" and isinstance(support.get("noul"), (int, float)),
        isinstance(ready.get("confidence"), (int, float)),
        isinstance(weak.get("confidence"), (int, float)),
        isinstance(usage.get("cost"), (int, float))
    ]
    if not all(checks):
        raise ApiProblem(502, "Jev returned an unexpected answer shape.", raw)
    score = round(ready["score"] / 4 * 70 + support["noul"] * 30, 1)
    return {
        "pageId": page["id"], "title": page["title"], "url": page["url"], "content": page["content"],
        "fetchedAt": page["fetchedAt"], "httpStatus": page["httpStatus"], "source": page["source"],
        "score": score, "readiness": ready["score"], "confidence": ready["confidence"],
        "weakest": weak["choice"], "weakestConfidence": weak["confidence"],
        "support": support["noul"], "cost": usage["cost"], "latencyMs": round(elapsed),
        "model": raw.get("model", MODEL_ID), "requestId": raw.get("id", "unavailable")
    }


def read_request(handler):
    length = int(handler.headers.get("Content-Length", "0"))
    if length <= 0 or length > 200_000:
        raise ApiProblem(400, "Request body must be between 1 and 200000 bytes.")
    try:
        return json.loads(handler.rfile.read(length))
    except json.JSONDecodeError as error:
        raise ApiProblem(400, "Request body must be valid JSON.") from error


class AuditHandler(SimpleHTTPRequestHandler):
    def send_json(self, status, payload):
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_POST(self):
        try:
            body = read_request(self)
            if self.path == "/api/discover":
                website_url = body.get("websiteUrl")
                if not isinstance(website_url, str) or not website_url.strip():
                    raise ApiProblem(400, "Enter a public website URL.")
                root_url, policy = load_policy(website_url)
                pages, sitemaps, notice = discover_pages(root_url, policy)
                self.send_json(200, {
                    "websiteUrl": root_url, "robotsUrl": policy["robotsUrl"], "sitemapUrls": sitemaps,
                    "crawlDelay": policy["delay"], "pages": pages, "notice": notice
                })
                return
            if self.path == "/api/audit":
                page = body.get("page")
                if not isinstance(page, dict) or any(not isinstance(page.get(field), str) or not page[field].strip() for field in ("id", "title", "url")):
                    raise ApiProblem(400, "Request must contain page.id, page.title, and page.url.")
                draft = body.get("draftContent")
                started = time.perf_counter()
                if draft is None:
                    safe_url = validate_public_url(page["url"])
                    host = canonical_host(urlsplit(safe_url).hostname)
                    policy = SITE_POLICIES.get(host)
                    if not policy:
                        raise ApiProblem(400, "Discover this website before auditing its pages.")
                    audit_page = extract_page({**page, "url": safe_url}, policy)
                else:
                    if not isinstance(draft, str) or not 80 <= len(draft.strip()) <= MAX_TEXT_CHARS:
                        raise ApiProblem(400, "Draft content must contain between 80 and 20000 characters.")
                    audit_page = {
                        **page, "content": draft.strip(), "fetchedAt": utc_now(),
                        "httpStatus": None, "source": "local_draft"
                    }
                result = normalize(audit_page, call_jev(audit_page), (time.perf_counter() - started) * 1000)
                self.send_json(200, result)
                return
            raise ApiProblem(404, "Not found")
        except ApiProblem as error:
            self.send_json(error.status, {"error": {"message": error.message, "details": error.details or {}}})
        except Exception as error:
            self.send_json(500, {"error": {"message": f"Unexpected server error: {error}", "details": {}}})


if __name__ == "__main__":
    load_env()
    server = ThreadingHTTPServer((HOST, PORT), AuditHandler)
    print(f"Jev GEO Audit running at http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server.")
    finally:
        server.server_close()
