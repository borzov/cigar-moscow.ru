"""Parse public archive listings. Network stays in the command."""

from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup

HOSTS = {"www.cigar-moscow.ru", "cigar-moscow.ru"}
TRACKING = {"gclid", "fbclid", "yclid"}


def normalize(url, base="https://www.cigar-moscow.ru/"):
    """Return the path and semantic query, or None for an external URL."""
    absolute = urljoin(base, url.strip())
    parts = urlsplit(absolute)
    host = (parts.hostname or "").lower()
    if parts.scheme not in {"http", "https", ""} or (host and host not in HOSTS):
        return None
    path = (parts.path or "/").lower()
    if not path.startswith("/"):
        path = "/" + path
    query = []
    for name, value in parse_qsl(parts.query, keep_blank_values=True):
        key = name.lower()
        if key.startswith("utm_") or key in TRACKING:
            continue
        query.append((key, value))
    query.sort()
    encoded = urlencode(query)
    return path + (("?" + encoded) if encoded else "")


def _title_and_date(block):
    header = block.select_one(".headerTxt") or block.select_one(".header")
    if header is None:
        return "", ""
    date_node = header.select_one(".date")
    published = ""
    if date_node is not None:
        published = date_node.get_text(" ", strip=True).removeprefix("//").strip()
        date_node.extract()
    return " ".join(header.get_text(" ", strip=True).split()), published


def parse_listing(raw, page_url):
    """Read teaser blocks, pager links and category labels from one listing."""
    if isinstance(raw, str):
        raw = raw.encode("cp1251")
    document = BeautifulSoup(raw.decode("cp1251"), "html5lib")
    page = normalize(page_url, page_url)
    items = []
    for block in document.select(".mainItemCell .newsItem, .mainItemCell .newsSmall, .anons_item"):
        anchor = block.select_one(".imgPrev a[href], .header a[href], .newsLink a[href]")
        if anchor is None:
            continue
        target = normalize(anchor["href"], page_url)
        if not target:
            continue
        query = dict(parse_qsl(urlsplit(target).query))
        item_id = query.get("item_id", "")
        if not item_id.isdigit():
            continue
        title, published = _title_and_date(block)
        section = urlsplit(target).path.rsplit("/", 1)[-1].removesuffix(".html")
        items.append({
            "item_id": int(item_id),
            "section": section,
            "url": target,
            "title": title,
            "date": published,
            "category": query.get("category"),
        })
    pages = []
    categories = []
    for anchor in document.select("a[href]"):
        target = normalize(anchor["href"], page_url)
        if not target or target == page:
            continue
        query = dict(parse_qsl(urlsplit(target).query))
        text = " ".join(anchor.get_text(" ", strip=True).split())
        if "item_id" not in query and ("from" in query or query.get("show_all") == "1"):
            if target not in pages:
                pages.append(target)
        category = query.get("category")
        if category and category.isdigit() and "item_id" not in query and text:
            categories.append({"id": category, "url": target, "title": text})
    return {"page": page, "items": items, "pages": pages, "categories": categories}


def _prefer_title(current, title):
    if title and (not current or len(title) > len(current)):
        return title
    return current


def add_listing(registry, parsed, category_id=None):
    """Merge one parsed listing into the registry. The same item_id stays one material."""
    items = registry.setdefault("items", {})
    pages = registry.setdefault("pages", {})
    categories = registry.setdefault("categories", {})
    page = parsed["page"]
    pages.setdefault(page, {"kind": "listing", "section": _section_name(page)})
    for extra in parsed["pages"]:
        pages.setdefault(extra, {
            "kind": "duplicate",
            "section": _section_name(page),
            "duplicate_of": page,
        })
    for item in parsed["items"]:
        key = str(item["item_id"])
        current = items.setdefault(key, {
            "item_id": item["item_id"],
            "section": item["section"],
            "title": "",
            "date": "",
            "urls": [],
            "categories": [],
            "scripts": [],
        })
        if item["url"] not in current["urls"]:
            current["urls"].append(item["url"])
        if item["section"] not in current["scripts"]:
            current["scripts"].append(item["section"])
        current["title"] = _prefer_title(current["title"], item["title"])
        if item["date"] and not current["date"]:
            current["date"] = item["date"]
        category = category_id or item.get("category")
        if category and category not in current["categories"]:
            current["categories"].append(category)
        pages.setdefault(item["url"], {"kind": "article", "item_id": item["item_id"]})
    for category in parsed["categories"]:
        stored = categories.setdefault(category["id"], {"id": category["id"], "title": "", "urls": []})
        stored["title"] = _prefer_title(stored["title"], category["title"])
        if category["url"] not in stored["urls"]:
            stored["urls"].append(category["url"])
        pages.setdefault(category["url"], {"kind": "category", "category": category["id"]})


def _section_name(page):
    path = urlsplit(page).path.rsplit("/", 1)[-1]
    return path.removesuffix(".html")
