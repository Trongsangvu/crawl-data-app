#!/usr/bin/env python3
"""
Universal Web Crawler
Supports: HTML/website crawling and REST API crawling
Output: Plain text files
Usage:
    python crawler.py --mode html --url https://example.com --depth 2
    python crawler.py --mode api  --url https://api.example.com/data --pages 5
"""
from datetime import datetime
from urllib.parse import urljoin, urlparse
import argparse
import time
import json
import re
import sys
import chardet

try:
    from curl_cffi import requests as curl_requests
    from bs4 import BeautifulSoup
except ImportError:
    print("Missing dependencies. Install with:")
    print("  pip install curl_cffi beautifulsoup4 chardet")
    sys.exit(1)


# ─── Helpers ────────────────────────────────────────────────────────────────


def timestamp():
    """TimeStamp"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def safe_get(url, session, timeout=10, retries=3, delay=1.0):
    """GET with retry + polite delay."""
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, timeout=timeout, impersonate="chrome124")

            resp.raise_for_status()
            time.sleep(delay)
            return resp
        except Exception as e:
            print(f"[attempt {attempt}/{retries}] Error: {e}")
            if attempt < retries:
                time.sleep(delay * attempt)

    return None


def decode_response(resp):
    """Detect encoding and decode response bytes to string."""
    detected = chardet.detect(resp.content)
    encoding = detected.get("encoding") or "utf-8"
    return resp.content.decode(encoding, errors="replace")


# ─── HTML / Website Crawler ─────────────────────────────────────────────────


def crawl_html(start_url, max_depth, output_file, delay, same_domain_only):
    """Crawl HTML"""
    visited = set()
    queue = [(start_url, 0)]
    base_domain = urlparse(start_url).netloc

    session = curl_requests.Session()

    lines = []
    lines.append("HTML Crawl Report")
    lines.append(f"Start URL   : {start_url}")
    lines.append(f"Max Depth   : {max_depth}")
    lines.append(f"Same Domain : {same_domain_only}")
    lines.append(f"Started At  : {timestamp()}")
    lines.append("=" * 70)
    lines.append("")

    page_count = 0

    while queue:
        url, depth = queue.pop(0)
        if url in visited or depth > max_depth:
            continue
        visited.add(url)

        print(f"[depth {depth}] Crawling: {url}")
        resp = safe_get(url, session, delay=delay)
        if resp is None:
            lines.append(f"[FAILED] {url}\n")
            continue

        html = decode_response(resp)
        soup = BeautifulSoup(html, "html.parser")

        # Extract page data
        title = soup.title.get_text(strip=True) if soup.title else "(no title)"

        meta_desc = ""
        meta_tag = soup.find("meta", attrs={"name": "description"})
        if meta_tag:
            content = meta_tag.get("content", "")
            meta_desc = str(content).strip() if content else ""

        # Body text (clean)
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        body_text = re.sub(r"\s+", " ", soup.get_text(separator=" ")).strip()
        body_preview = body_text[:500] + ("..." if len(body_text) > 500 else "")

        # Outbound links
        links = []
        for a in soup.find_all("a", href=True):
            raw = a.get("href", "")
            if not raw:
                continue
            href = urljoin(url, str(raw).strip())
            parsed = urlparse(href)
            if parsed.scheme not in ("http", "https"):
                continue
            if same_domain_only and parsed.netloc != base_domain:
                continue
            links.append(href)
            if href not in visited:
                queue.append((href, depth + 1))

        page_count += 1
        lines.append(f"Page #{page_count}")
        lines.append(f"  URL     : {url}")
        lines.append(f"  Title   : {title}")
        if meta_desc:
            lines.append(f"  Meta    : {meta_desc}")
        lines.append(f"  Depth   : {depth}")
        lines.append(f"  Links   : {len(set(links))} found")
        lines.append(f"  Preview : {body_preview}")
        lines.append("")

    lines.append("=" * 70)
    lines.append(f"Finished At  : {timestamp()}")
    lines.append(f"Total Pages  : {page_count}")
    lines.append(f"Total Visited: {len(visited)}")

    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"\nDone. {page_count} pages saved to: {output_file}")


# ─── API Crawler ────────────────────────────────────────────────────────────


def crawl_api(
    base_url,
    pages,
    output_file,
    delay,
    pagination_param,
    page_start,
    headers_extra,
    json_path,
):
    """Crawl API"""
    session = curl_requests.Session()
    session.headers.update({"Accept": "application/json", "User-Agent": "Mozilla/5.0"})
    if headers_extra:
        for kv in headers_extra:
            k, v = kv.split(":", 1)
            session.headers[k.strip()] = v.strip()

    lines = []
    lines.append("API Crawl Report")
    lines.append(f"Base URL    : {base_url}")
    lines.append(f"Pages       : {pages}")
    lines.append(f"Param       : {pagination_param}")
    lines.append(f"Started At  : {timestamp()}")
    lines.append("=" * 70)
    lines.append("")

    total_records = 0

    for page_num in range(page_start, page_start + pages):
        sep = "&" if "?" in base_url else "?"
        url = f"{base_url}{sep}{pagination_param}={page_num}"

        print(f"[page {page_num}] Fetching: {url}")
        resp = safe_get(url, session, delay=delay)
        if resp is None:
            lines.append(f"[FAILED] page {page_num} — {url}\n")
            continue

        try:
            data = resp.json()
        except json.JSONDecodeError:
            lines.append(f"[NON-JSON] page {page_num}\n{resp.text[:300]}\n")
            continue

        # Optionally extract nested list via dot-path  e.g. "results" or "data.items"
        records = data
        if json_path:
            for key in json_path.split("."):
                if isinstance(records, dict) and key in records:
                    records = records[key]
                else:
                    records = None
                    break

        lines.append(f"--- Page {page_num} ---")
        lines.append(f"  URL: {url}")

        if isinstance(records, list):
            lines.append(f"  Records: {len(records)}")
            total_records += len(records)
            for i, item in enumerate(records, 1):
                if isinstance(item, dict):
                    lines.append(
                        f"  [{i}] " + " | ".join(f"{k}: {v}" for k, v in item.items())
                    )
                else:
                    lines.append(f"  [{i}] {item}")
        else:
            # Scalar or dict response — dump key/value pairs
            if isinstance(data, dict):
                for k, v in data.items():
                    lines.append(f"  {k}: {v}")
            else:
                lines.append(f"  {data}")
        lines.append("")

    lines.append("=" * 70)
    lines.append(f"Finished At    : {timestamp()}")
    lines.append(f"Total Pages    : {pages}")
    lines.append(f"Total Records  : {total_records}")

    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(
        f"\nDone. {total_records} records across {pages} pages saved to: {output_file}"
    )


# ─── CLI ────────────────────────────────────────────────────────────────────


def main():
    """Run Script Main"""
    parser = argparse.ArgumentParser(
        description="Universal Web Crawler — HTML & API modes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Crawl a website up to depth 2, stay on same domain
  python crawler.py --mode html --url https://example.com --depth 2

  # Crawl a public API across 5 pages, extract nested list at "results"
  python crawler.py --mode api --url https://api.example.com/items \\
      --pages 5 --json-path results

  # API with auth header and custom pagination param
  python crawler.py --mode api --url https://api.example.com/posts \\
      --pages 3 --pagination-param page --header "Authorization: Bearer TOKEN"
        """,
    )

    parser.add_argument(
        "--mode",
        choices=["html", "api"],
        required=True,
        help="Crawl mode: html (website) or api (REST JSON)",
    )
    parser.add_argument("--url", required=True, help="Starting URL to crawl")
    parser.add_argument(
        "--output", default="", help="Output .txt file (default: crawl_<timestamp>.txt)"
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Seconds to wait between requests (default: 1.0)",
    )

    # HTML-specific
    parser.add_argument(
        "--depth", type=int, default=2, help="[html] Max crawl depth (default: 2)"
    )
    parser.add_argument(
        "--all-domains",
        action="store_true",
        help="[html] Follow links to external domains too",
    )

    # API-specific
    parser.add_argument(
        "--pages",
        type=int,
        default=5,
        help="[api] Number of pages to fetch (default: 5)",
    )
    parser.add_argument(
        "--pagination-param",
        default="page",
        help="[api] Query param name for pagination (default: page)",
    )
    parser.add_argument(
        "--page-start", type=int, default=1, help="[api] First page number (default: 1)"
    )
    parser.add_argument(
        "--header",
        action="append",
        dest="headers",
        metavar="KEY:VALUE",
        help="[api] Extra request header, e.g. 'Authorization: Bearer TOKEN'",
    )
    parser.add_argument(
        "--json-path",
        default="",
        help="[api] Dot-path to records list in JSON, e.g. 'data.items'",
    )

    args = parser.parse_args()

    output = args.output or f"crawl_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

    if args.mode == "html":
        crawl_html(
            start_url=args.url,
            max_depth=args.depth,
            output_file=output,
            delay=args.delay,
            same_domain_only=not args.all_domains,
        )
    else:
        crawl_api(
            base_url=args.url,
            pages=args.pages,
            output_file=output,
            delay=args.delay,
            pagination_param=args.pagination_param,
            page_start=args.page_start,
            headers_extra=args.headers or [],
            json_path=args.json_path,
        )


if __name__ == "__main__":
    main()
