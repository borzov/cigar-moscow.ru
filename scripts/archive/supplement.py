#!/usr/bin/env python3
"""Add the CMS pages and files the public section crawl never reached.

The eight spirit essays and the named festival reports stay in the same
snapshot as the rest of the archive. Office files that were never linked
from a page become their own journal records, so a later import does not
rewrite a journal an editor has already touched.
"""

from html import escape
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup

import fetch
from planner import redact_sensitive, slugify
from snapshot import BASE, Limiter, http_bytes, read_json, save_json

SPIRIT = (194, 195, 196, 224, 228, 295, 299, 435)
REPORTS = (
    "del_habano_1", "del_habano_2", "del_habano_3", "del_habano_4", "del_habano_5",
    "del_habano_6", "del_habano_7", "del_habano_8", "del_habano_9", "del_habano_10",
    "19_02_2011", "20_02_2011", "21_02_2011", "21_02_2011_2", "22_02_2011",
    "23_02_2011", "23_02_2011_2", "24_02_2011", "24_02_2011_2", "24_02_2011_3",
    "25_02_2011", "present_2011_02_21", "habano_2011",
    "IPCPR_before", "IPCPR_1st_day", "IPCPR_2nd_day", "IPCPR_3rd_day", "IPCPR_4th_day",
    "it2010", "Inter_tabac_2011", "inter_tabac_23_09_2011", "25_09_2011", "26_09_2011",
    "2011_05_27_01", "2011_05_27_02", "2011_06_25_01", "2011_06_25_02",
    "2011_08_25_1", "2011_08_25_2",
)
OFFICE = {".doc", ".docx", ".ppt", ".pptx", ".txt", ".mov", ".pdf"}
HOST = os.environ.get("CLUB_ARCHIVE_SSH", "")
SSH_KEY = Path(os.environ.get("CLUB_ARCHIVE_SSH_KEY", Path.home() / ".ssh/id_ed25519"))
SSH = ["ssh", "-i", str(SSH_KEY), "-o", "IdentitiesOnly=yes", "-o", "ConnectTimeout=25", HOST]
REMOTE_PULL = "cigar-moscow.ru/tmp/pull"


def page_token(name):
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return "page-" + slug


def guessed_date(name, images, text):
    for pattern in (r"(\d{4})_(\d{2})_(\d{2})", r"(\d{2})_(\d{2})_(\d{4})"):
        match = re.search(pattern, name)
        if not match:
            continue
        parts = match.groups()
        if len(parts[0]) == 4:
            year, month, day = parts
        else:
            day, month, year = parts
        if 1 <= int(month) <= 12 and 1 <= int(day) <= 31:
            return f"{year}-{month}-{day}"
    for image in images:
        match = re.search(r"(20\d{2}-\d{2}-\d{2})", image)
        if match:
            return match.group(1)
    from planner import prose_date
    return prose_date(text) or ""


def supplement(root, limiter=None):
    limiter = limiter or Limiter()
    registry = read_json(root / "registry.json")
    registry.setdefault("documents", {})
    articles = root / "articles"
    originals = root / "originals"
    assets = read_json(root / "assets.json")
    attachments = read_json(root / "attachments.json")
    report = read_json(root / "extraction-report.json")
    failed = report.setdefault("failed_media", {})
    before = set(failed)
    _spirit(root, registry, limiter, originals, articles)
    _reports(root, registry, limiter, originals, articles)
    _eurotab(registry)
    recovered = _files(root, registry, articles, assets, attachments, failed)
    report["failed_media"] = failed
    save_json(root / "registry.json", registry)
    save_json(root / "assets.json", assets)
    save_json(root / "attachments.json", attachments)
    save_json(root / "extraction-report.json", report)
    save_json(root / "recovered.json", sorted(recovered))
    write_admin_list(root, failed)
    print(
        f"Supplement ready. Recovered {len(recovered)} files that were missing "
        f"({len(before)} gaps before this pass, {len(failed)} remain)."
    )


def _spirit(root, registry, limiter, originals, articles):
    for item_id in SPIRIT:
        key = str(item_id)
        registry["items"][key] = {
            "categories": [],
            "date": registry["items"].get(key, {}).get("date", ""),
            "item_id": item_id,
            "scripts": ["cigar_news"],
            "section": "spirit",
            "title": registry["items"].get(key, {}).get("title", ""),
            "urls": [f"/cigar_news.html?item_id={item_id}"],
        }
        registry["pages"][f"/cigar_news.html?item_id={item_id}"] = {"kind": "article", "item_id": item_id}
        destination = articles / f"{item_id}.json"
        if destination.exists():
            record = read_json(destination)
        else:
            page = f"{BASE}cigar_news.html?item_id={item_id}"
            body, error = http_bytes(page, originals / f"{item_id}.html", limiter)
            if error or body is None:
                raise RuntimeError(f"Spirit essay {item_id} did not open: {error}")
            record, _alts, _pdfs, _metrics = fetch.extract(
                BeautifulSoup(body.decode("cp1251"), "html5lib"), page, item_id,
                allow_empty=True, strict_template=False,
            )
            record["body"], _changed = redact_sensitive(record["body"])
            save_json(destination, record)
        registry["items"][key]["title"] = record["title"]
        registry["items"][key]["date"] = record.get("date") or ""
        print(f"Spirit {item_id}: {record['title']}", flush=True)


def _reports(root, registry, limiter, originals, articles):
    if len(REPORTS) != 39:
        raise RuntimeError(f"Expected 39 named reports, found {len(REPORTS)}")
    for name in REPORTS:
        token = page_token(name)
        url = f"{BASE}{name}.html"
        destination = articles / f"{token}.json"
        if destination.exists():
            record = read_json(destination)
        else:
            body, error = http_bytes(url, originals / f"{token}.html", limiter)
            if error or body is None:
                raise RuntimeError(f"Report {name} did not open: {error}")
            record, _alts, pdfs, _metrics = fetch.extract_document(
                BeautifulSoup(body.decode("cp1251"), "html5lib"), url, token,
            )
            record["date"] = guessed_date(name, record["images"], BeautifulSoup(record["body"], "html.parser").get_text(" ", strip=True))
            record["body"], _changed = redact_sensitive(record["body"])
            record["attachments"] = pdfs
            save_json(destination, record)
        registry["documents"][token] = {
            "item_id": token,
            "section": "cigar_news",
            "title": record["title"],
            "date": record.get("date") or "",
            "urls": [f"/{name}.html"],
            "source": f"/{name}.html",
            "categories": [],
        }
        registry["pages"][f"/{name}.html"] = {"kind": "document", "item_id": token}
        print(f"Report {name}: {record['title']}", flush=True)


def _eurotab(registry):
    """The public page repeats news 271. One journal, two old addresses."""
    item = registry["items"]["271"]
    extra = "/eurotab2011.html"
    if extra not in item["urls"]:
        item["urls"] = [*item["urls"], extra]
    registry["pages"][extra] = {"kind": "article", "item_id": 271}


def _register_office(root, registry, articles, found):
    known = _known_paths(root, {})
    used = set(registry["documents"])
    for entry in found:
        path = entry["path"]
        suffix = Path(path).suffix.lower()
        if entry.get("status") != "office" or suffix not in OFFICE or entry.get("size", 0) <= 0:
            continue
        if path.casefold() in known:
            continue
        url = fetch.request_url("https://www.cigar-moscow.ru/" + path.lstrip("/"))
        token = _file_token(Path(path).name, used)
        used.add(token)
        title = Path(path).stem
        date = ""
        match = re.search(r"(20\d{2}-\d{2}-\d{2})", path)
        if match:
            date = match.group(1)
        record = {
            "title": title,
            "date": date,
            "url": url,
            "body": f'<p><a href="{escape(url, quote=True)}">{escape(Path(path).name)}</a></p>',
            "images": [],
            "preview": None,
            "attachments": [url],
            "warnings": [
                "Файл лежал на сервере рядом с материалами и не был вставлен в статью. "
                "Запись создана отдельно, уже импортированный текст не переписывается."
            ],
        }
        save_json(articles / f"{token}.json", record)
        registry["documents"][token] = {
            "item_id": token,
            "section": "cigar_news",
            "title": title,
            "date": date,
            "urls": [],
            "source": urlsplit(url).path,
            "categories": [],
        }
        entry["url"] = url
        entry["keep"] = True
        print(f"Office {token}: {path}", flush=True)


def _file_token(filename, used):
    stem = Path(filename).stem
    slug = slugify(stem)
    if slug == "cigar":
        slug = "dokument"
    token = "file-" + slug[:70].strip("-")
    candidate = token
    number = 2
    while candidate in used:
        candidate = f"{token}-{number}"
        number += 1
    return candidate


def _known_paths(root, attachments):
    known = set()
    for path in (root / "articles").glob("*.json"):
        record = read_json(path)
        for url in [*(record.get("images") or []), record.get("preview"), *(record.get("attachments") or [])]:
            if url:
                known.add(unquote(urlsplit(url).path).lstrip("/").casefold())
        for link in BeautifulSoup(record.get("body") or "", "html.parser").select("a[href]"):
            href = link.get("href") or ""
            if href.startswith("http"):
                known.add(unquote(urlsplit(href).path).lstrip("/").casefold())
    for url in attachments:
        known.add(unquote(urlsplit(url).path).lstrip("/").casefold())
    return known


def _files(root, registry, articles, assets, attachments, failed):
    """Store bytes for new pages and for addresses that failed the first crawl."""
    wanted = {}
    for path in (root / "articles").glob("*.json"):
        record = read_json(path)
        for url in record.get("images") or []:
            wanted.setdefault(url, "assets")
        if record.get("preview"):
            wanted.setdefault(record["preview"], "assets")
        for url in record.get("attachments") or []:
            wanted.setdefault(url, "attachments")
    for url in list(failed):
        folder = "attachments" if Path(unquote(urlsplit(url).path)).suffix.lower() in OFFICE else "assets"
        if folder == "assets" and not fetch.IMAGE.search(urlsplit(url).path):
            continue
        wanted.setdefault(url, folder)
    recovered = []
    pending = []
    wayback = Path.home() / ".local/share/cigar-moscow/wayback-recovered"
    local_case = Path.home() / ".local/share/cigar-moscow/live-site"
    for url, folder in sorted(wanted.items()):
        if _present(root, assets, attachments, url):
            if url in failed:
                failed.pop(url, None)
                recovered.append(url)
            continue
        rel = unquote(urlsplit(url).path).lstrip("/")
        local = _local_copy(wayback, local_case, url, rel)
        if local is not None and local.stat().st_size > 0:
            _keep(root, assets, attachments, failed, recovered, url, folder, local.read_bytes())
            continue
        if urlsplit(url).hostname not in {"www.cigar-moscow.ru", "cigar-moscow.ru"}:
            continue
        pending.append({"url": url, "path": rel, "folder": folder})
    pulled = _pull(root, pending)
    _register_office(root, registry, articles, pulled)
    by_path = {item["path"].casefold(): item for item in pulled if item.get("status") != "office"}
    for item in pending:
            found = by_path.get(item["path"].casefold())
            if not found or found.get("status") != "found":
                reason = "Empty file on the server" if found and found.get("status") == "empty" else "Not on the server"
                failed.setdefault(item["url"], reason)
                continue
            blob = (root / "pull" / found["pull"]).read_bytes()
            _keep(root, assets, attachments, failed, recovered, item["url"], item["folder"], blob)
    for entry in pulled:
        if entry.get("status") != "office" or not entry.get("url") or not entry.get("pull"):
            continue
        blob = (root / "pull" / entry["pull"]).read_bytes()
        _keep(root, assets, attachments, failed, recovered, entry["url"], "attachments", blob)
    pull = root / "pull"
    if pull.exists():
        import shutil
        shutil.rmtree(pull)
    return recovered


def _present(root, assets, attachments, url):
    entry = assets.get(url) or attachments.get(url)
    return bool(entry and (root / entry["file"]).is_file())


def _local_copy(wayback, local_case, url, rel):
    host = urlsplit(url).hostname or ""
    candidates = [
        wayback / host / rel,
        local_case / rel,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _keep(root, assets, attachments, failed, recovered, url, folder, blob):
    try:
        data = fetch.store_bytes(root, folder, url, blob)
    except ValueError as error:
        failed[url] = str(error)
        return
    target = attachments if folder == "attachments" else assets
    other = assets if folder == "attachments" else attachments
    other.pop(url, None)
    target[url] = data
    if url in failed:
        failed.pop(url, None)
        recovered.append(url)


def _pull(root, pending):
    paths = sorted({item["path"] for item in pending})
    script = r"""
import os, sys, json, hashlib, shutil
root = os.path.expanduser("~/cigar-moscow.ru/www")
dest = os.path.expanduser("~/cigar-moscow.ru/tmp/pull")
if os.path.isdir(dest):
    shutil.rmtree(dest)
os.makedirs(dest)
wanted = json.load(sys.stdin)
result = []
seen = set()
def add(rel, actual, size):
    status = "empty" if size == 0 else "found"
    name = ""
    if status == "found":
        suffix = os.path.splitext(actual)[1].lower()
        name = hashlib.sha256(rel.encode("utf-8")).hexdigest() + suffix
        shutil.copyfile(os.path.join(root, actual), os.path.join(dest, name))
    result.append({"path": rel, "actual": actual, "size": size, "status": status, "pull": name})
    seen.add(actual.lower())
for rel in wanted:
    direct = os.path.join(root, rel)
    if os.path.isfile(direct):
        add(rel, rel, os.path.getsize(direct))
        continue
    parent = os.path.dirname(direct)
    base = os.path.basename(rel).lower()
    match = ""
    if os.path.isdir(parent):
        for entry in os.listdir(parent):
            if entry.lower() == base:
                match = os.path.join(os.path.dirname(rel), entry)
                break
    if match:
        add(rel, match, os.path.getsize(os.path.join(root, match)))
    else:
        result.append({"path": rel, "status": "missing", "size": 0, "pull": ""})
office = (b".doc", b".docx", b".ppt", b".pptx", b".txt", b".mov", b".pdf")
start = os.path.join(root, "content").encode("ascii")
for dirpath, _dirs, names in os.walk(start):
    for name in names:
        lower = name.lower()
        if not lower.endswith(office):
            continue
        full = os.path.join(dirpath, name)
        rel = os.path.relpath(full, root.encode("ascii"))
        try:
            text = rel.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = rel.decode("cp1251")
            except UnicodeDecodeError:
                continue
        if text.lower() in seen:
            continue
        size = os.path.getsize(full)
        if size <= 0:
            continue
        suffix = os.path.splitext(text)[1].lower()
        pull = hashlib.sha256(text.encode("utf-8")).hexdigest() + suffix
        shutil.copyfile(full, os.path.join(dest.encode("ascii"), pull.encode("ascii")))
        result.append({"path": text, "actual": text, "size": size, "status": "office", "pull": pull})
json.dump(result, sys.stdout)
"""
    return _pull_split(root, paths, script)


def _pull_split(root, paths, script):
    if not HOST:
        raise RuntimeError("Set CLUB_ARCHIVE_SSH to the hosting account before pulling files")
    remote_script = script.replace("json.load(sys.stdin)", "json.load(open(os.path.expanduser('~/cigar-moscow.ru/tmp/wanted.json')))")
    payload = json.dumps(paths)
    send = subprocess.run([*SSH, "cat > cigar-moscow.ru/tmp/wanted.json"], input=payload, text=True, capture_output=True)
    if send.returncode != 0:
        raise RuntimeError(send.stderr.strip() or "Could not send the file list")
    run = subprocess.run([*SSH, "python3", "-"], input=remote_script, text=True, capture_output=True)
    if run.returncode != 0:
        raise RuntimeError(run.stderr.strip() or "Remote file lookup failed")
    # stdout may include an SSH warning on stderr only. stdout is JSON.
    listing = json.loads(run.stdout)
    subprocess.run(
        ["scp", "-i", str(SSH_KEY), "-o", "IdentitiesOnly=yes", "-r",
         f"{HOST}:{REMOTE_PULL}", str(root / "pull")],
        check=True,
    )
    subprocess.run([*SSH, f"rm -rf {REMOTE_PULL} cigar-moscow.ru/tmp/wanted.json"], check=False)
    return listing


def write_admin_list(root, failed):
    titles = {}
    for path in (root / "articles").glob("*.json"):
        record = read_json(path)
        label = record.get("title") or path.stem
        page = record.get("url") or ""
        for url in [*(record.get("images") or []), record.get("preview"), *(record.get("attachments") or [])]:
            if url:
                titles.setdefault(url, (label, page))
        for link in BeautifulSoup(record.get("body") or "", "html.parser").select("a[href], img[src]"):
            href = link.get("href") or link.get("src") or ""
            if href:
                titles.setdefault(href, (label, page))
    groups = {}
    for url, reason in sorted(failed.items()):
        label, page = titles.get(url, ("Страница не определена", ""))
        groups.setdefault((label, page), []).append((url, reason))
    lines = [
        "Недостающие файлы www.cigar-moscow.ru",
        "Список составлен 24 ноября 2026 после переноса публичных страниц, восьми винных очерков,",
        "дневников фестивалей и файлов, которые нашлись на диске сервера или в Wayback.",
        "",
        "Ниже только то, чего в сохранённой копии нет. Если оригинал найдётся,",
        "его можно положить по тому же адресу: имя и папка должны совпасть.",
        "",
        f"Всего адресов: {len(failed)}.",
        "",
    ]
    for (label, page), rows in sorted(groups.items(), key=lambda item: item[0][0].casefold()):
        lines.append(label)
        if page:
            lines.append(f"Страница: {page}")
        for url, reason in rows:
            note = _reason(reason)
            lines.append(f"- {url}" + (f" — {note}" if note else ""))
        lines.append("")
    destination = Path(__file__).resolve().parents[2] / "archive-missing-for-admin.txt"
    destination.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"Admin list: {destination}")


def _reason(reason):
    text = reason or ""
    if "Empty file" in text or "0 bytes" in text:
        return "на сервере файл есть, но он пустой"
    if "Not on the server" in text or "404" in text:
        return "на сервере файла нет"
    if "outside the pilot source" in text:
        return "адрес на чужом сайте, не в каталоге клуба"
    if "Unexpected content" in text:
        return "файл скачался, но это не изображение и не документ"
    return ""


def main():
    root = Path(os.environ.get("CLUB_ARCHIVE_DIR", Path.home() / ".local/share/cigar-moscow/archive"))
    supplement(root)


if __name__ == "__main__":
    main()
