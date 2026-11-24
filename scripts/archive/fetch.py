#!/usr/bin/env python3
"""Retrieve the fixed MA archive pilot. Requires beautifulsoup4==4.14.3, html5lib==1.1."""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
import http.client
from urllib.parse import parse_qs, quote, unquote, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup, Comment

BASE = "https://www.cigar-moscow.ru/"
SECTIONS = {"anons": (879, 883), "cigar_news": (886, 887, 888), "tasting": (111, 123, 146, 102, 298)}
IMAGE = re.compile(r"\.(?:jpe?g|gif|png|webp)$", re.I)
ALLOWED = set("a p div span h1 h2 h3 h4 h5 h6 br hr strong em b i u s sup sub blockquote ol ul li table thead tbody tfoot tr th td caption img".split())
BLOCKS = set("p div h1 h2 h3 h4 h5 h6 br hr blockquote ol ul li table thead tbody tfoot tr th td caption".split())


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_bytes(data)
    temporary.replace(path)


def save_json(path, value):
    write(path, (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode())


def local_source(url):
    parts = urlsplit(url)
    return parts.scheme in {"http", "https"} and parts.hostname in {"www.cigar-moscow.ru", "cigar-moscow.ru"}


def request_url(url):
    """Encode a legacy path without changing a URL that is already safe."""
    parts = urlsplit(url.strip())
    return urlunsplit((
        parts.scheme,
        parts.netloc,
        quote(unquote(parts.path), safe="/"),
        quote(unquote(parts.query), safe="=&;%+"),
        "",
    ))


def fetch(url, path):
    if path.exists():
        return path.read_bytes()
    if not local_source(url):
        raise ValueError("Resource outside the pilot source")
    target = request_url(url)
    for attempt in range(3):
        try:
            with urlopen(Request(target, headers={"User-Agent": "MA-Archive-Local-Pilot/1.0"}), timeout=30) as res:
                if not local_source(res.url):
                    raise ValueError("Unexpected cross-site redirect")
                data = res.read()
            break
        except (HTTPError, URLError, TimeoutError, ConnectionError) as error:
            if attempt == 2 or (isinstance(error, HTTPError) and error.code not in {429, 500, 502, 503, 504}):
                raise
            time.sleep(2 ** attempt)
    write(path, data)
    return data


def original(root, filename, url):
    raw = fetch(url, root / "originals" / filename)
    return BeautifulSoup(raw.decode("windows-1251"), "html5lib")


def absolute(base, source):
    return urljoin(base, source.strip())


def structure(body):
    """Track text, block sequence and original image positions around words."""
    words = []
    ordered = []
    for node in body.descendants:
        if node.name in BLOCKS:
            ordered.append(node.name)
        elif node.name == "img":
            ordered.append([len(words), node["src"]])
        elif node.name is None and not isinstance(node, Comment):
            words.extend(str(node).split())
    return words, ordered


def same_reading(before, after):
    """True when cleanup kept the characters and the image order.

    A mailto link that is unwrapped can glue a following comma to the address.
    That is still the same text. A missing word or a moved image is not.
    """
    def pack(value):
        words, ordered = value
        images = [item[1] for item in ordered if isinstance(item, list)]
        return "".join(words), images
    return pack(before) == pack(after)


def extract(doc, url, item, *, allow_empty=False, strict_template=True):
    article = doc.select_one(".mainItemCell .newsItem")
    heading = article.select_one(":scope > .header .headerTxt") if article else None
    if heading is None:
        raise ValueError(f"Unexpected article template for {item}")
    date_node = heading.select_one(".date")
    if date_node is None:
        if strict_template:
            raise ValueError(f"Missing publication date for {item}")
        timestamp = ""
    else:
        timestamp = date_node.extract().get_text(strip=True).removeprefix("//").strip()
        if timestamp:
            date.fromisoformat(timestamp)
    title = heading.get_text(" ", strip=True)
    generated_title = False
    if not title:
        generated_title = True
        title = f"Материал {item}"
    body = article.select_one(":scope > .Txt")
    preview = article.select_one(":scope > .imgPrev img")
    preview_url = absolute(url, preview["src"]) if preview else None
    if not body or (strict_template and (generated_title or not body.select(".category"))):
        raise ValueError(f"Unexpected article template for {item}")
    for node in body.select(".category, script, style, iframe, form, object, embed, noscript"):
        node.decompose()
    for node in body.find_all(string=lambda s: isinstance(s, Comment)):
        node.extract()

    warnings = []
    if generated_title:
        warnings.append("У страницы нет заголовка. Поставлено служебное название.")
    if item in {879, 883}:
        warnings.append("Historical promotion, prices or commercial offers; editorial review required.")
    if item == 888:
        warnings.append("Historical sponsor acknowledgments in the gala report.")
    if item == 883:
        # Remove the historical payment instructions together with personal contact details.
        sensitive = [p for p in body.select("p") if "перевода на карту" in p.get_text(" ", strip=True)]
        if len(sensitive) != 1:
            raise ValueError("Expected one historical payment paragraph for 883")
        sensitive[0].clear()
        sensitive[0].string = "[Архивные платёжные и контактные данные удалены.]"
        warnings.append("One historical payment/contact paragraph redacted.")
    images_in_source = len(body.find_all("img"))
    hidden_gallery_labels = 0
    gallery_targets = []
    attachments = []
    for link in list(body.find_all("a", href=True)):
        target = absolute(url, link["href"])
        path = urlsplit(target).path
        if IMAGE.search(path) and local_source(target) and link.get("rel"):
            # The legacy lightbox hides most of its image links with inline CSS.
            # Make those images available in document order without its JavaScript.
            hidden = link.find_parent(style=lambda s: s and re.search(r"display\s*:\s*none", s, re.I))
            if hidden:
                link.clear()
                hidden_gallery_labels += 1
            image = doc.new_tag("img", src=target, alt="")
            link.append(image)
            gallery_targets.append(target)
            link.unwrap()
        elif target.startswith(("http://", "https://")):
            link["href"] = target
            if path.lower().endswith(".pdf"):
                attachments.append(target)
        else:
            link.unwrap()

    for img in body.find_all("img"):
        img["src"] = absolute(url, img["src"])
    # Compare article text, semantic blocks and image positions before and after
    # removing layout attributes. Only explicit transformations above may differ.
    expected = structure(body)
    for tag in list(body.find_all(True)):
        if tag.name not in ALLOWED:
            tag.unwrap()
            continue
        keep = {"img": ("src", "alt"), "a": ("href",), "td": ("colspan", "rowspan"), "th": ("colspan", "rowspan", "scope"), "ol": ("start",)}.get(tag.name, ())
        tag.attrs = {key: tag[key] for key in keep if tag.has_attr(key)}
        if tag.name == "img":
            tag.attrs.setdefault("alt", "")
    clean = body.decode_contents().strip()
    output = BeautifulSoup('<div id="body">' + clean + "</div>", "html5lib").select_one("#body")
    if not same_reading(expected, structure(output)):
        raise ValueError(f"Body text or image positions changed for {item}")
    images = [img["src"] for img in output.select("img")]
    if len(images) != images_in_source + len(gallery_targets):
        raise ValueError(f"Unexpected number of images for {item}")
    if not expected[0] and not (allow_empty and images):
        raise ValueError(f"Missing body text for {item}")
    record = {"title": title, "date": timestamp, "url": url, "body": clean, "images": images, "preview": preview_url}
    if warnings:
        record["warnings"] = warnings
    image_alts = {img["src"]: img.get("alt", "") for img in output.select("img")}
    if preview:
        image_alts.setdefault(preview_url, preview.get("alt", ""))
    metrics = {
        "source_body_images": images_in_source, "lightbox_targets": len(gallery_targets),
        "hidden_lightbox_labels_removed": hidden_gallery_labels, "output_images": len(images),
        "normalized_words": len(expected[0]), "normalized_text_sha256": sha256(" ".join(expected[0]).encode()).hexdigest(),
        "elements": dict(Counter(tag.name for tag in output.find_all(True))), "review": warnings,
    }
    return record, image_alts, attachments, metrics


def download_asset(task):
    root, folder, url, alt = task
    # Preserve ext and use the full URL's hash, since many galleries reuse names.
    suffix = Path(unquote(urlsplit(url).path)).suffix.lower()
    rel = Path(folder) / (sha256(url.encode()).hexdigest() + suffix)
    try:
        raw = fetch(url, root / rel)
        mime = None
        for prefix, kind in [(b"\xff\xd8\xff", "image/jpeg"), (b"\x89PNG\r\n\x1a\n", "image/png"), (b"GIF87a", "image/gif"), (b"GIF89a", "image/gif"), (b"%PDF-", "application/pdf")]:
            if raw.startswith(prefix):
                mime = kind
                break
        if raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
            mime = "image/webp"
        if not mime or (folder == "assets") != mime.startswith("image/"):
            (root / rel).unlink()
            raise ValueError(f"Unexpected content signature ({len(raw)} bytes)")
        data = {"file": rel.as_posix(), "sha256": sha256(raw).hexdigest(), "bytes": len(raw), "mime": mime}
        if alt:
            data["alt"] = alt
        return folder, url, data, None
    except (OSError, ValueError, http.client.HTTPException) as error:
        return folder, url, None, str(error)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    root = parser.parse_args().output
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    variants = {}
    category = BASE + "news.html?category=27"
    festival_ids = {str(i) for i in SECTIONS["anons"] + SECTIONS["cigar_news"]}
    for filename, url in [("category-27.html", category), ("category-27-all.html", category + "&show_all=1"), ("category-27-news.html", BASE + "cigar_news.html?category=27")]:
        doc = original(root, filename, url)
        listed = {parse_qs(urlsplit(a["href"]).query).get("item_id", [None])[0]
                  for a in doc.select(".mainItemCell .imgPrev a[href]")}
        if listed != festival_ids:
            raise ValueError(f"Unexpected category membership in {filename}: {listed}")
        for a in doc.select(".mainItemCell a[href]"):
            target = absolute(url, a["href"])
            item = parse_qs(urlsplit(target).query).get("item_id", [None])[0]
            if item in festival_ids:
                variants.setdefault(item, set()).add(target)
    rating_url = BASE + "rating.html"
    rating = original(root, "rating.html", rating_url)
    tasting_ids = {str(i) for i in SECTIONS["tasting"]}
    for link in rating.select(".mainItemCell a[href]"):
        target = absolute(rating_url, link["href"])
        item = parse_qs(urlsplit(target).query).get("item_id", [None])[0]
        if item in tasting_ids:
            variants.setdefault(item, set()).add(target)
    media, attachments, metrics = {}, set(), {}
    for section, ids in SECTIONS.items():
        for item in ids:
            url = f"{BASE}{section}.html?item_id={item}"
            doc = original(root, f"{item}.html", url)
            record, alts, pdfs, metrics[str(item)] = extract(doc, url, item)
            for img, alt in alts.items():
                media[img] = media.get(img) or alt
            attachments.update(pdfs)
            variants.setdefault(str(item), set()).add(url)
            save_json(root / "articles" / f"{item}.json", record)
    save_json(root / "legacy-urls.json", {item: sorted(paths) for item, paths in variants.items()})
    tasks = [(root, "assets", url, alt) for url, alt in sorted(media.items())]
    tasks += [(root, "attachments", url, "") for url in sorted(attachments)]
    manifests = {"assets": {}, "attachments": {}}
    failures = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for folder, url, data, error in pool.map(download_asset, tasks):
            if error:
                failures[url] = error
            else:
                manifests[folder][url] = data
    for folder, manifest in manifests.items():
        save_json(root / (folder + ".json"), manifest)
    save_json(root / "extraction-report.json", {"articles": metrics, "failed_media": failures})
    print(f"{len(metrics)} articles, {len(manifests['assets'])} images, {len(manifests['attachments'])} PDFs, {len(failures)} missing.")
    inventory = json.loads(Path(__file__).with_name("pilot-inventory.json").read_text())
    known_missing = {url for urls in inventory["missing"].values() for url in urls}
    return int(any(url not in known_missing or not re.search(r"\b(404|410)\b", error)
                   for url, error in failures.items()))


if __name__ == "__main__":
    raise SystemExit(main())
