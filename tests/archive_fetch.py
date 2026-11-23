"""Verify the downloaded pilot independently against its original HTML. Usage: python tests/archive_fetch.py OUTPUT."""

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup


def verify(root):
    read = lambda name: json.loads((root / name).read_text(encoding="utf-8"))
    images, attachments = read("assets.json"), read("attachments.json")
    failed = read("extraction-report.json")["failed_media"]
    required_images, required_pdf = set(), set()
    selected = {102, 111, 123, 146, 298, 879, 883, 886, 887, 888}
    records = sorted((root / "articles").glob("*.json"))
    assert {int(p.stem) for p in records} == selected
    for path in records:
        item = int(path.stem)
        article = json.loads(path.read_text(encoding="utf-8"))
        doc = BeautifulSoup((root / "originals" / f"{item}.html").read_bytes().decode("cp1251"), "html5lib")
        source = doc.select_one(".mainItemCell .newsItem > .Txt")
        rendered = BeautifulSoup(article["body"], "html5lib").body
        preview = doc.select_one(".mainItemCell .newsItem > .imgPrev img")
        assert article["preview"] == urljoin(article["url"], preview["src"])
        required_images.add(article["preview"])
        for share in source.select(".category, script, style, iframe, noscript"):
            share.decompose()

        # The lightbox used invisible links. Their action labels were never
        # visible article text, but their target photographs are article media.
        old_images = [urljoin(article["url"], img["src"]) for img in source.select("img[src]")]
        for anchor in source.select("a[rel][href]"):
            old_images.append(urljoin(article["url"], anchor["href"]))
            if anchor.find_parent(style=lambda s: s and re.search(r"display\s*:\s*none", s, re.I)):
                anchor.clear()
        if item == 883:
            sensitive = next(p for p in source.select("p") if "перевода на карту" in p.get_text())
            sensitive.string = "[Архивные платёжные и контактные данные удалены.]"
            assert not re.search(r"(?:\d[ -]*){16}|[\w.-]+@[\w.-]+", rendered.get_text(" "))
        assert source.get_text(" ", strip=True).split() == rendered.get_text(" ", strip=True).split(), item
        assert Counter(old_images) == Counter(article["images"]), item
        assert [tag["src"] for tag in rendered.select("img")] == article["images"], item
        assert not rendered.select("script, iframe, form, object, embed, [style], [onclick]")
        assert not re.search(r"(?:Р.|С.){4,}|\ufffd", article["title"] + rendered.get_text(" "))
        required_images.update(article["images"])
        for link in rendered.select("a[href]"):
            dest = urlsplit(link["href"])
            assert dest.scheme in {"http", "https"}
            if dest.path.lower().endswith(".pdf"):
                required_pdf.add(link["href"])

    assert (set(images) | set(attachments)).isdisjoint(failed)
    assert required_images | required_pdf == set(images) | set(attachments) | set(failed)
    for entry in [*images.values(), *attachments.values()]:
        content = (root / entry["file"]).read_bytes()
        assert len(content) == entry["bytes"] and sha256(content).hexdigest() == entry["sha256"], entry["file"]
    assert len(required_images) == 645 and len(required_pdf) == 4
    print(f"{len(records)} originals matched, {len(images)} images + {len(attachments)} PDFs verified, {len(failed)} unavailable URLs accounted for.")


if __name__ == "__main__":
    verify(Path(sys.argv[1]))
