"""Download the public archive and build the Drupal plan. Raw pages stay outside Git."""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urljoin, urlsplit

from bs4 import BeautifulSoup

import fetch
from listing import add_listing, normalize, parse_listing
from planner import PILOT_ARTICLES, _canonical, build_plan, parse_rating, redact_sensitive

BASE = "https://www.cigar-moscow.ru/"
SECTIONS = (
    "cigar_news.html", "tasting.html", "anons.html", "journey.html", "cigar_raritet.html",
    "humidor.html", "cigar_portrait.html", "okurok.html", "gallery.html",
)
PILOT_ROOT = Path.home() / ".local/share/cigar-moscow/pilot-2016/snapshot"
REPO = Path(__file__).resolve().parents[2]


class Limiter:
    def __init__(self, interval=0.25):
        self.interval = interval
        self.lock = threading.Lock()
        self.nxt = 0.0

    def wait(self):
        with self.lock:
            delay = self.nxt - time.time()
            if delay > 0:
                time.sleep(delay)
            self.nxt = time.time() + self.interval


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def http_bytes(url, path, limiter):
    limiter.wait()
    try:
        return fetch.fetch(url, path), None
    except HTTPError as error:
        return None, f"HTTP {error.code}"
    except (URLError, TimeoutError, ConnectionError, OSError, ValueError) as error:
        return None, str(error)


def inventory(root, limiter):
    """Walk section indexes once and store the unique-item registry."""
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    listings = root / "listings"
    listings.mkdir(exist_ok=True)
    registry = {"items": {}, "pages": {}, "categories": {}}
    home, error = http_bytes(BASE, listings / "home.html", limiter)
    if error:
        raise RuntimeError(f"Homepage unavailable: {error}")
    add_listing(registry, parse_listing(home, BASE))
    for section in SECTIONS:
        page = f"{BASE}{section}?show_all=1"
        body, error = http_bytes(page, listings / f"{section}.html", limiter)
        if error:
            raise RuntimeError(f"{section} unavailable: {error}")
        parsed = parse_listing(body, page)
        add_listing(registry, parsed)
        _spot_check(section, parsed, registry, listings, limiter)
    for category_id in sorted(registry["categories"]):
        page = f"{BASE}news.html?category={category_id}&show_all=1"
        body, error = http_bytes(page, listings / f"category-{category_id}.html", limiter)
        if error:
            raise RuntimeError(f"Category {category_id} unavailable: {error}")
        add_listing(registry, parse_listing(body, page), category_id=category_id)
    rating, error = http_bytes(BASE + "rating.html", listings / "rating.html", limiter)
    if error:
        raise RuntimeError(f"Rating unavailable: {error}")
    registry["pages"]["/rating.html"] = {"kind": "index", "section": "rating"}
    for static in ("/contacts.html", "/Inter_Tabac_2010.html"):
        registry["pages"].setdefault(normalize(static), {"kind": "static"})
    counts = Counter()
    for item in registry["items"].values():
        for script in item["scripts"]:
            counts[script] += 1
    registry["summary"] = {
        "unique_items": len(registry["items"]),
        "by_script": dict(sorted(counts.items())),
        "source": "public-pages",
        "cms_dump": False,
        "content_directory": False,
    }
    save_json(root / "registry.json", registry)
    print(
        f"Unique materials: {registry['summary']['unique_items']}. "
        f"By script: {registry['summary']['by_script']}. "
        "Public pages only; no legacy CMS dump and no content/ directory."
    )
    return registry


def _spot_check(section, parsed, registry, listings, limiter):
    offsets = []
    for page in parsed["pages"]:
        query = dict(parse_qsl(urlsplit(page).query))
        if query.get("from", "").isdigit():
            offsets.append(int(query["from"]))
    if not offsets:
        return
    missing = False
    for offset in (min(offsets), max(offsets)):
        page = f"{BASE}{section}?show_all=0&from={offset}"
        body, error = http_bytes(page, listings / f"{section}-{offset}.html", limiter)
        if error or body is None:
            continue
        extra = parse_listing(body, page)
        if any(str(item["item_id"]) not in registry["items"] for item in extra["items"]):
            missing = True
            break
    if not missing:
        return
    for offset in sorted(set(offsets)):
        page = f"{BASE}{section}?show_all=0&from={offset}"
        body, error = http_bytes(page, listings / f"{section}-{offset}.html", limiter)
        if body:
            add_listing(registry, parse_listing(body, page))


def fetch_articles(root, limiter, limit=0):
    """Save cleaned articles and files. Existing files and pilot originals are reused."""
    registry = read_json(root / "registry.json")
    articles_dir = root / "articles"
    originals = root / "originals"
    articles_dir.mkdir(exist_ok=True)
    originals.mkdir(mode=0o700, exist_ok=True)
    os.chmod(originals, 0o700)
    pilot_files, pilot_failures = _pilot_media()
    known_failures = {}
    report_path = root / "extraction-report.json"
    if report_path.exists():
        known_failures = {
            url: reason for url, reason in read_json(report_path).get("failed_media", {}).items()
            if "404" in reason or "410" in reason
        }
    items = [registry["items"][key] for key in sorted(registry["items"], key=lambda value: int(value))]
    if limit:
        items = items[:limit]
    media, attachments, failures, metrics = {}, set(), dict(known_failures), {}
    for index, item in enumerate(items, start=1):
        record = _article(root, item, originals, articles_dir, limiter, failures, metrics)
        if record is None:
            continue
        for image in record.get("images") or []:
            media.setdefault(image, "")
        if record.get("preview"):
            media.setdefault(record["preview"], "")
        for link in BeautifulSoup(record.get("body") or "", "html.parser").select("a[href]"):
            href = link["href"]
            if urlsplit(href).path.lower().endswith(".pdf"):
                attachments.add(href)
        if index % 25 == 0:
            print(f"Articles {index}/{len(items)}", flush=True)
    manifests = {"assets": {}, "attachments": {}}
    tasks = [(root, "assets", url, alt, pilot_files, pilot_failures, limiter) for url, alt in sorted(media.items())]
    tasks += [(root, "attachments", url, "", pilot_files, pilot_failures, limiter) for url in sorted(attachments)]
    with ThreadPoolExecutor(max_workers=3) as pool:
        for done, (folder, url, data, error) in enumerate(pool.map(_stage, tasks), start=1):
            if error:
                failures[url] = error
            elif data:
                manifests[folder][url] = data
            if done % 500 == 0:
                print(f"Files {done}/{len(tasks)}", flush=True)
    for folder, manifest in manifests.items():
        save_json(root / f"{folder}.json", manifest)
    save_json(report_path, {"articles": metrics, "failed_media": failures})
    _write_inventory(root)
    print(
        f"Articles saved, {len(manifests['assets'])} images, "
        f"{len(manifests['attachments'])} attachments, {len(failures)} missing or failed."
    )


def _pilot_media():
    if not PILOT_ROOT.exists():
        return {}, {}
    files = read_json(PILOT_ROOT / "assets.json")
    files.update(read_json(PILOT_ROOT / "attachments.json"))
    failures = read_json(PILOT_ROOT / "extraction-report.json").get("failed_media", {})
    return files, failures


def _article(root, item, originals, articles_dir, limiter, failures, metrics):
    item_id = int(item["item_id"])
    destination = articles_dir / f"{item_id}.json"
    pilot_article = PILOT_ROOT / "articles" / f"{item_id}.json"
    if item_id in PILOT_ARTICLES and pilot_article.exists():
        if not destination.exists() or destination.read_bytes() != pilot_article.read_bytes():
            shutil.copyfile(pilot_article, destination)
        return read_json(destination)
    if destination.exists():
        return _with_redaction(destination, read_json(destination))
    page = urljoin(BASE, _canonical(item))
    body, error = http_bytes(page, originals / f"{item_id}.html", limiter)
    if error or body is None:
        failures[f"article:{item_id}"] = error or "empty response"
        return None
    try:
        record, _alts, _pdfs, metrics[str(item_id)] = fetch.extract(
            BeautifulSoup(body.decode("cp1251"), "html5lib"), page, item_id,
            allow_empty=True, strict_template=False,
        )
    except (ValueError, AttributeError) as error:
        failures[f"article:{item_id}"] = str(error)
        return None
    return _with_redaction(destination, record)


def _with_redaction(destination, record):
    cleaned, _changed = redact_sensitive(record.get("body") or "")
    if cleaned == record.get("body"):
        if not destination.exists():
            save_json(destination, record)
        return record
    updated = {**record, "body": cleaned}
    save_json(destination, updated)
    return updated


def _stage(task):
    try:
        return _stage_one(task)
    except Exception as error:
        return task[1], task[2], None, str(error)


def _stage_one(task):
    root, folder, url, alt, pilot_files, pilot_failures, limiter = task
    if url in pilot_failures:
        return folder, url, None, pilot_failures[url]
    pilot = pilot_files.get(url)
    if pilot and (PILOT_ROOT / pilot["file"]).is_file():
        target = root / pilot["file"]
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copyfile(PILOT_ROOT / pilot["file"], target)
        return folder, url, pilot, None
    limiter.wait()
    return fetch.download_asset((root, folder, url, alt))


def _write_inventory(root):
    articles = {}
    for path in sorted((root / "articles").glob("*.json")):
        articles[path.stem] = sha256(path.read_bytes()).hexdigest()
    report = read_json(root / "extraction-report.json")
    missing = {}
    for path in sorted((root / "articles").glob("*.json")):
        record = read_json(path)
        urls = [*(record.get("images") or []), record.get("preview"), *record.get("attachments", [])]
        gone = [url for url in urls if url and url in report.get("failed_media", {})]
        if gone:
            missing[path.stem] = gone
    unassigned = [url for url in report.get("failed_media", {}) if url.startswith("http") and not any(url in group for group in missing.values())]
    if unassigned:
        missing["unassigned"] = unassigned
    save_json(root / "inventory.json", {"articles": articles, "missing": missing})


def preview(root):
    registry = read_json(root / "registry.json")
    articles = {path.stem: read_json(path) for path in (root / "articles").glob("*.json")}
    rating = parse_rating((root / "listings" / "rating.html").read_bytes())
    pilot = read_json(REPO / "scripts" / "archive" / "pilot.json")
    omitted = read_json(REPO / "scripts" / "archive" / "pilot-evidence.json").get("omitted", {})
    media = {
        "assets": read_json(root / "assets.json") if (root / "assets.json").exists() else {},
        "attachments": read_json(root / "attachments.json") if (root / "attachments.json").exists() else {},
        "missing": read_json(root / "extraction-report.json").get("failed_media", {}) if (root / "extraction-report.json").exists() else {},
    }
    plan = build_plan(registry, articles, rating, pilot, omitted, media)
    uncovered = sorted(set(registry["pages"]) - set(plan["outcomes"]["pages"]))
    if uncovered:
        raise RuntimeError("Pages without a result: " + ", ".join(uncovered[:10]))
    save_json(root / "plan" / "records.json", plan["records"])
    save_json(root / "plan" / "questions.json", plan["questions"])
    save_json(root / "plan" / "outcomes.json", plan["outcomes"])
    _write_inventory(root)
    counts = Counter(row["type"] for row in plan["records"])
    results = Counter(page["result"] for page in plan["outcomes"]["pages"].values())
    print(f"Records by type: {dict(counts)}. Page results: {dict(results)}. Questions: {len(plan['questions'])}.")
    return plan
