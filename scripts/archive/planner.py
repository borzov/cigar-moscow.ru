"""Turn a saved archive snapshot into Drupal records and an editor's question list."""

from copy import deepcopy
from datetime import date
from html import unescape
import re
import unicodedata
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup

PILOT_ARTICLES = {102, 111, 123, 146, 298, 879, 883, 886, 887, 888}
RUBRIC = {
    "cigar_news": "club", "anons": "club", "tasting": "club", "gallery": "club", "news": "club",
    "journey": "travel", "cigar_portrait": "portrait", "cigar_raritet": "vintage",
    "humidor": "humidor", "okurok": "digest",
}
FESTIVAL_TITLE = re.compile(
    r"fest|habano|championship|puro sabor|сигарна[яю]\s+волна|белый парус|procigar",
    re.I,
)
COMMERCIAL = re.compile(
    r"(?:\d[\d\s]{2,}\s*(?:руб\.?|₽|usd|eur|\$|€))"
    r"|(?:стоимость|прайс-лист|прайс\b|спонсорск\w+\s+пакет|цена\s+участия|рекламн\w+\s+пакет)",
    re.I,
)
SENSITIVE = re.compile(
    r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"
    r"|(?:\+7|8)[\s().-]*\d{3}[\s().-]*\d{3}[\s().-]*\d{2}[\s().-]*\d{2}"
    r"|(?:\d[ -]*?){13,19}"
)
MONTHS = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
    "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}
COUNTRIES = {
    "куба": "Куба", "доминикана": "Доминиканская Республика", "никарагуа": "Никарагуа",
    "гондурас": "Гондурас", "мексика": "Мексика", "сша": "США", "бразилия": "Бразилия",
    "ямайка": "Ямайка", "филиппины": "Филиппины", "индонезия": "Индонезия",
    "италия": "Италия", "испания": "Испания", "германия": "Германия",
    "швейцария": "Швейцария", "нидерланды": "Нидерланды", "голландия": "Нидерланды",
    "перу": "Перу", "коста-рика": "Коста-Рика", "эквадор": "Эквадор", "канада": "Канада",
    "франция": "Франция", "бельгия": "Бельгия", "великобритания": "Великобритания",
}
STOP = set("y de la el del by the and of для на от из".split())
PILOT_FESTIVAL = {"27": "legacy:festival-2016"}


def plain(fragment):
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def redact_sensitive(html):
    """Replace payment and contact tokens in visible text. Leave file addresses alone."""
    soup = BeautifulSoup(html or "", "html.parser")
    changed = 0
    for node in list(soup.find_all(string=True)):
        if getattr(node.parent, "name", None) in {"script", "style"}:
            continue
        source = str(node)
        if not SENSITIVE.search(source):
            continue
        cleaned = SENSITIVE.sub("[данные удалены]", source)
        if cleaned != source:
            node.replace_with(cleaned)
            changed += 1
    for link in soup.find_all("a", href=True):
        if link["href"].lower().startswith(("mailto:", "tel:")):
            link["href"] = "#"
            changed += 1
    return "".join(str(child) for child in soup.contents), changed


def tokens(name):
    text = unicodedata.normalize("NFKD", name.lower().replace("ё", "е"))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return [word for word in re.findall(r"[a-z0-9а-я]+", text) if word not in STOP and len(word) > 1]


def _score(name, title_tokens):
    words = tokens(name)
    if not words:
        return 0
    found = len(set(words) & title_tokens)
    if words[-1] in title_tokens:
        found += 2
    return found


def names_compatible(cigar, title, siblings):
    """Accept a rating name when the title supports it better than a rival vitola."""
    words = tokens(cigar)
    title_tokens = set(tokens(title))
    if not words or not (set(words) & title_tokens):
        return False
    if words[-1] in title_tokens:
        return True
    if not siblings:
        return False
    own = _score(cigar, title_tokens)
    best = max(_score(other, title_tokens) for other in siblings)
    if own < best:
        return False
    return bool(set(words[:-1]) & title_tokens)


def slugify(name):
    words = tokens(name)
    slug = "-".join(words)[:80].strip("-")
    return slug or "cigar"


def prose_date(text):
    match = re.search(
        r"\b(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+(\d{4})",
        text,
        re.I,
    )
    if not match:
        return None
    day, month, year = int(match.group(1)), MONTHS[match.group(2).lower()], int(match.group(3))
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def score_number(text):
    if re.fullmatch(r"\d{1,3}", text or "") and 0 <= int(text) <= 100:
        return int(text)
    return None


def interpret_scores(collective, individual):
    """Keep the written score. Fill a number only when the column is unambiguous."""
    club = [item["score"].strip() for item in collective]
    person = [item["score"].strip() for item in individual]
    parts = []
    if club:
        parts.append("коллективная: " + ", ".join(club))
    if person:
        parts.append("индивидуальная: " + ", ".join(person))
    fields = {"field_score_original": "; ".join(parts)}
    question = None
    if len(club) == 1 and not person:
        number = score_number(club[0])
        if number is None:
            question = f"Составная оценка «{club[0]}» оставлена исходной записью без числовых полей."
        else:
            fields["field_club_score"] = number
    elif len(person) == 1 and not club:
        number = score_number(person[0])
        if number is None:
            question = f"Индивидуальная оценка «{person[0]}» оставлена исходной записью без числового поля."
        else:
            fields["field_individual_score"] = number
    elif len(club) == 1 and len(person) == 1 and club[0] == person[0]:
        question = (
            f"В обеих колонках рейтинга одна запись «{club[0]}». "
            "Числа не заполнены, пока клуб не подтвердит, какая колонка чему соответствует."
        )
    elif len(club) == 1 and len(person) == 1 and score_number(club[0]) is not None and score_number(person[0]) is not None:
        fields["field_club_score"] = score_number(club[0])
        fields["field_individual_score"] = score_number(person[0])
    else:
        question = f"Оценки ({fields['field_score_original']}) не разложены по полям. Нужна редакционная расшифровка."
    return fields, question


def parse_rating(raw):
    text = raw.decode("cp1251") if isinstance(raw, bytes) else raw
    rows = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", text, re.I | re.S):
        cells = re.findall(r"<td\b[^>]*>(.*?)</td>", row, re.I | re.S)
        if len(cells) != 5 or not plain(cells[0]).isdigit():
            continue
        rows.append({
            "rank": plain(cells[0]),
            "cigar": plain(cells[1]),
            "country": plain(cells[2]),
            "collective": _score_links(cells[3]),
            "individual": _score_links(cells[4]),
        })
    return rows


def _score_links(cell):
    links = re.findall(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', cell, re.I | re.S)
    return [{"score": plain(label), "href": unescape(href)} for href, label in links]


def _item_id(href):
    values = parse_qs(urlsplit(href).query).get("item_id", [])
    return int(values[0]) if values and values[0].isdigit() else None


def _pilot_index(records):
    by_item = {}
    for row in records:
        ids = set()
        if isinstance(row.get("article"), int):
            ids.add(row["article"])
        for source in [row.get("source"), *(row.get("redirects") or [])]:
            found = _item_id(source or "")
            if found:
                ids.add(found)
        for source_id in row.get("images_from") or []:
            ids.add(int(source_id))
        for item in ids:
            by_item.setdefault(item, []).append(row["id"])
    return by_item


def _canonical(item):
    section = item.get("section") or ""
    for url in item.get("urls") or []:
        if urlsplit(url).path.endswith(f"/{section}.html") or urlsplit(url).path.endswith(f"{section}.html"):
            return url
    return (item.get("urls") or ["/"])[0]


def build_plan(registry, articles, rating_rows, pilot_records, omitted, media):
    """Return records, questions and a result for every registry page."""
    records = [deepcopy(row) for row in pilot_records]
    questions = []
    for rank, text in sorted(omitted.items()):
        questions.append({"id": f"pilot-omitted-{rank}", "subject": f"rating:{rank}", "question": text})
    pilot_items = _pilot_index(records)
    used_slugs = {}
    for row in records:
        if row["type"] == "cigar":
            used_slugs[slugify(row.get("title") or row["id"])] = row["id"]
    festivals = {}
    for category_id, category in sorted(registry.get("categories", {}).items()):
        if not FESTIVAL_TITLE.search(category.get("title") or ""):
            continue
        if category_id in PILOT_FESTIVAL:
            festivals[category_id] = PILOT_FESTIVAL[category_id]
            continue
        festivals[category_id] = f"legacy:festival:category-{category_id}"
    new = {"festival": [], "cigar": [], "event": [], "album": [], "journal": [], "tasting": []}
    outcomes = {}
    made = {}
    for key in sorted(registry.get("items", {}), key=lambda value: int(value)):
        item = registry["items"][key]
        item_id = int(item["item_id"])
        if item_id in pilot_items:
            made[item_id] = _pilot_outcome(item_id, pilot_items[item_id], records)
            continue
        article = articles.get(str(item_id))
        if not article:
            made[item_id] = {"result": "skip", "reason": "Страница есть в списке, но текст не скачан.", "records": []}
            questions.append({
                "id": f"missing-article-{item_id}",
                "subject": f"item:{item_id}",
                "question": f"Материал {item_id} не удалось прочитать. Повторить загрузку или взять его из резервной копии?",
            })
            continue
        for index, note in enumerate(article.get("warnings") or []):
            questions.append({
                "id": f"warning-{item_id}-{index}",
                "subject": f"legacy:journal:{item_id}",
                "question": note,
            })
        made[item_id] = _plan_item(item, article, new, questions, festivals, used_slugs)
    _plan_ratings(rating_rows, registry, articles, new, questions, made, used_slugs)
    _festival_records(registry, articles, festivals, new, questions, records)
    records.extend(new["festival"])
    records.extend(new["cigar"])
    records.extend(new["event"])
    records.extend(new["album"])
    records.extend(new["journal"])
    records.extend(new["tasting"])
    _unique_redirects(records, questions)
    pages = _page_outcomes(registry, festivals, made, records)
    files = _file_outcomes(media)
    return {"records": records, "questions": questions, "outcomes": {"pages": pages, "files": files}}


def _unique_redirects(records, questions):
    seen = {}
    for row in records:
        if not row.get("published", True):
            continue
        kept = []
        for source in row.get("redirects") or []:
            owner = seen.get(source)
            if owner and owner != row["id"]:
                questions.append({
                    "id": f"redirect-{row['id']}-{len(questions)}",
                    "subject": row["id"],
                    "question": f"Адрес {source} уже ведёт к {owner}. Второе перенаправление не назначено.",
                })
                continue
            seen[source] = row["id"]
            kept.append(source)
        if kept:
            row["redirects"] = kept
        elif "redirects" in row:
            del row["redirects"]


def _pilot_outcome(item_id, record_ids, records):
    aliases = [row["alias"] for row in records if row["id"] in record_ids and row.get("published", True)]
    return {"result": "records", "records": list(record_ids), "aliases": aliases, "preserved": True}


def _plan_item(item, article, new, questions, festivals, used_slugs):
    item_id = int(item["item_id"])
    original = article.get("body") or ""
    body, redacted = redact_sensitive(original)
    commercial = bool(COMMERCIAL.search(plain(original)))
    published = not commercial
    if redacted or "[данные удалены]" in original:
        questions.append({
            "id": f"redacted-{item_id}",
            "subject": f"legacy:journal:{item_id}",
            "question": "Из текста удалён фрагмент с телефоном, почтой или номером карты. Проверьте, что соседние фразы на месте.",
        })
    if commercial:
        questions.append({
            "id": f"commercial-{item_id}",
            "subject": f"legacy:journal:{item_id}",
            "question": "В тексте есть цена или пакет участия. Материал оставлен черновиком для редакционной проверки.",
        })
    published_on = article.get("date") or item.get("date") or ""
    event_date = prose_date(plain(original)) or published_on
    category = _festival_category(item, festivals)
    festival_id = festivals.get(category) if category else None
    section = item.get("section") or "cigar_news"
    wants_event = section in {"tasting", "gallery"} or festival_id or len(article.get("images") or []) >= 8
    event_id = None
    if wants_event and event_date:
        event_id = f"legacy:event:{item_id}"
        new["event"].append({
            "id": event_id,
            "type": "event",
            "alias": f"/events/archive-{item_id}",
            "source": _canonical(item),
            "title": article.get("title") or item.get("title") or f"Встреча {item_id}",
            "body": "<p>Дата взята из текста или из даты публикации архива и требует подтверждения, если в материале нет отдельной даты встречи.</p>",
            "created": published_on or event_date,
            "published": published,
            "fields": {
                "field_date": event_date,
                "field_event_type": "world_festival" if festival_id else "club",
                **({"field_festival": {"ref": festival_id}} if festival_id else {}),
            },
        })
    album_id = None
    images = article.get("images") or []
    if event_id and (section == "gallery" or festival_id or len(images) >= 8) and images:
        album_id = f"legacy:album:{item_id}"
        new["album"].append({
            "id": album_id,
            "type": "album",
            "alias": f"/albums/archive-{item_id}",
            "source": _canonical(item),
            "title": (article.get("title") or item.get("title") or str(item_id)) + " · фотографии",
            "body": "<p>Порядок кадров сохранён из архивной страницы.</p>",
            "published": published,
            "fields": {
                "field_date": event_date,
                "field_event": {"ref": event_id},
                **({"field_festival": {"ref": festival_id}} if festival_id else {}),
            },
            "images_from": [item_id],
            "cover_from": item_id,
        })
    journal_id = f"legacy:journal:{item_id}"
    fields = {"field_rubrics": [{"slug": RUBRIC.get(section, "club")}]}
    if event_id:
        fields["field_event"] = {"ref": event_id}
    if festival_id:
        fields["field_festival"] = {"ref": festival_id}
    journal = {
        "id": journal_id,
        "type": "journal",
        "alias": f"/journal/archive-{item_id}",
        "source": _canonical(item),
        "article": item_id,
        "published": published,
        "created": published_on or None,
        "fields": fields,
        "cover_from": item_id,
    }
    if published:
        journal["redirects"] = list(item.get("urls") or [])
    else:
        journal.pop("redirects", None)
    new["journal"].append({key: value for key, value in journal.items() if value not in (None, "", [], {})})
    record_ids = [journal_id, *([event_id] if event_id else []), *([album_id] if album_id else [])]
    if published:
        return {"result": "records", "records": record_ids, "aliases": [f"/journal/archive-{item_id}"]}
    return {
        "result": "draft",
        "reason": "Цена, пакет участия или рекламная подача. Публичные перенаправления не назначены.",
        "records": record_ids,
    }


def _festival_category(item, festivals):
    matches = sorted(category for category in item.get("categories") or [] if category in festivals)
    return matches[0] if matches else None


def _plan_ratings(rows, registry, articles, new, questions, made, used_slugs):
    by_item = {}
    for row in rows:
        for link in row["collective"] + row["individual"]:
            item_id = _item_id(link["href"])
            if item_id:
                by_item.setdefault(item_id, []).append(row["cigar"])
    for row in rows:
        grouped = {}
        for kind, links in (("collective", row["collective"]), ("individual", row["individual"])):
            for link in links:
                item_id = _item_id(link["href"])
                if item_id is None or item_id in PILOT_ARTICLES:
                    continue
                grouped.setdefault(item_id, {"collective": [], "individual": []})[kind].append(link)
        for item_id, columns in grouped.items():
            item = registry.get("items", {}).get(str(item_id))
            article = articles.get(str(item_id))
            title = (article or {}).get("title") or (item or {}).get("title") or ""
            siblings = [name for name in by_item.get(item_id, []) if name != row["cigar"]]
            if title and not names_compatible(row["cigar"], title, siblings):
                questions.append({
                    "id": f"rating-mismatch-{row['rank']}-{item_id}",
                    "subject": f"rating:{row['rank']}",
                    "question": (
                        f"Рейтинг связывает «{row['cigar']}» со страницей «{title}» (материал {item_id}). "
                        "Карточка не создана: название не подтверждает эту витолу."
                    ),
                })
                continue
            fields, question = interpret_scores(columns["collective"], columns["individual"])
            slug = slugify(row["cigar"])
            cigar_id = used_slugs.get(slug) or f"legacy:cigar:{slug}"
            if slug not in used_slugs:
                used_slugs[slug] = cigar_id
                country = COUNTRIES.get(row["country"].strip().lower())
                cigar_fields = {}
                if country:
                    cigar_fields["field_country_term"] = {"term": country}
                elif row["country"].strip():
                    questions.append({
                        "id": f"country-{slug}",
                        "subject": cigar_id,
                        "question": f"Страна «{row['country']}» не сопоставлена со словарём. Под каким названием её записать?",
                    })
                source = _canonical(item) if item else (article or {}).get("url", "/")
                source = urlsplit(source).path + (("?" + urlsplit(source).query) if urlsplit(source).query else "")
                new["cigar"].append({
                    "id": cigar_id,
                    "type": "cigar",
                    "alias": f"/cigars/archive-{slug}",
                    "source": source if source.startswith("/") else "/",
                    "title": row["cigar"],
                    "body": "<p>Карточка собрана из строки архивного рейтинга. Марка и формат в таблице не выделены отдельно.</p>",
                    "fields": cigar_fields,
                })
            event_id = f"legacy:event:{item_id}"
            tasting_id = f"legacy:tasting:{item_id}:{row['rank']}"
            if question:
                questions.append({"id": f"score-{tasting_id}", "subject": tasting_id, "question": question})
            published_on = (article or {}).get("date") or (item or {}).get("date") or ""
            tasted = prose_date(plain((article or {}).get("body") or "")) or published_on
            if not tasted:
                questions.append({
                    "id": f"tasting-date-{tasting_id}",
                    "subject": tasting_id,
                    "question": f"У материала {item_id} нет даты дегустации. Карточка оценки не создана.",
                })
                continue
            if prose_date(plain((article or {}).get("body") or "")) is None:
                questions.append({
                    "id": f"tasting-date-assumed-{tasting_id}",
                    "subject": tasting_id,
                    "question": f"Дата дегустации материала {item_id} взята из даты публикации {tasted}. Подтвердите её.",
                })
            if not any(entry["id"] == event_id for entry in new["event"]):
                journal = next((entry for entry in new["journal"] if entry["id"] == f"legacy:journal:{item_id}"), None)
                new["event"].append({
                    "id": event_id,
                    "type": "event",
                    "alias": f"/events/archive-{item_id}",
                    "source": _canonical(item) if item else f"/tasting.html?item_id={item_id}",
                    "title": title or f"Дегустация {item_id}",
                    "body": "<p>Встреча собрана из строки рейтинга: отдельной страницы события в архиве не было.</p>",
                    "created": published_on or tasted,
                    "published": journal.get("published", True) if journal else True,
                    "fields": {"field_date": tasted, "field_event_type": "club"},
                })
                if journal is not None:
                    journal.setdefault("fields", {})["field_event"] = {"ref": event_id}
            tasting_fields = {
                "field_date": tasted,
                "field_cigar": {"ref": cigar_id},
                "field_score_original": fields["field_score_original"],
                "field_event": {"ref": event_id},
            }
            for name in ("field_club_score", "field_individual_score"):
                if name in fields:
                    tasting_fields[name] = fields[name]
            ambiguous = "field_club_score" not in fields and "field_individual_score" not in fields
            new["tasting"].append({
                "id": tasting_id,
                "type": "tasting",
                "alias": f"/tastings/archive-{item_id}-{row['rank']}",
                "source": f"/tasting.html?item_id={item_id}",
                "title": f"{row['cigar']} · {tasted}",
                "body": f"<p>Исходная запись баллов сохранена. <a href=\"/journal/archive-{item_id}\">Текст отчёта</a>.</p>",
                "created": published_on or tasted,
                "published": not ambiguous,
                "fields": tasting_fields,
            })
            journal = next((row for row in new["journal"] if row["id"] == f"legacy:journal:{item_id}"), None)
            if journal is not None:
                refs = journal.setdefault("fields", {}).setdefault("field_cigars", [])
                if {"ref": cigar_id} not in refs:
                    refs.append({"ref": cigar_id})
            outcome = made.setdefault(item_id, {"result": "records", "records": [], "aliases": []})
            if event_id not in outcome["records"]:
                outcome["records"].append(event_id)
            if tasting_id not in outcome["records"]:
                outcome["records"].append(tasting_id)
            if cigar_id not in outcome["records"]:
                outcome["records"].append(cigar_id)


def _festival_records(registry, articles, festivals, new, questions, existing):
    existing_ids = {row["id"] for row in existing}
    for category_id, festival_id in sorted(festivals.items()):
        if festival_id in existing_ids or any(row["id"] == festival_id for row in new["festival"]):
            continue
        dates = []
        for item in registry.get("items", {}).values():
            if category_id not in (item.get("categories") or []):
                continue
            article = articles.get(str(item["item_id"]), {})
            found = article.get("date") or item.get("date")
            if found:
                dates.append(found)
        if not dates:
            questions.append({
                "id": f"festival-date-{category_id}",
                "subject": festival_id,
                "question": f"У выпуска категории {category_id} нет ни одной даты. Запись выпуска не создана.",
            })
            continue
        start, end = min(dates), max(dates)
        category = registry["categories"][category_id]
        year = re.search(r"(19|20)\d{2}", category.get("title") or "")
        urls = [url for url in category.get("urls") or [] if "from=" not in url]
        record = {
            "id": festival_id,
            "type": "festival",
            "alias": f"/festival/category-{category_id}",
            "source": urls[0] if urls else f"/news.html?category={category_id}",
            "title": category.get("title") or f"Выпуск {category_id}",
            "body": "<p>Даты ниже — границы публикации архивных материалов, а не подтверждённая программа.</p>",
            "published": True,
            "fields": {"field_date": start, **({"field_end": end} if end != start else {}), **({"field_year": int(year.group(0))} if year else {})},
            "redirects": urls,
        }
        new["festival"].append(record)
        questions.append({
            "id": f"festival-bounds-{category_id}",
            "subject": festival_id,
            "question": f"Даты выпуска «{record['title']}» взяты из публикации материалов ({start} — {end}). Подтвердите программу.",
        })


def _page_outcomes(registry, festivals, made, records):
    by_id = {row["id"]: row for row in records}
    pages = {}
    for url, info in sorted(registry.get("pages", {}).items()):
        query = {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}
        if query.get("category", "").isdigit() and "item_id" not in query and "from" not in query:
            info = {**info, "kind": "category", "category": query["category"]}
        kind = info.get("kind")
        if kind == "article":
            outcome = made.get(int(info["item_id"]), {"result": "skip", "reason": "Нет решения по материалу.", "records": []})
            pages[url] = outcome
            continue
        if kind == "duplicate":
            pages[url] = {
                "result": "duplicate",
                "reason": f"Страница пагинации дублирует список {info.get('duplicate_of')}. Перенаправление не назначается.",
                "records": [],
            }
            continue
        if kind == "category":
            festival_id = festivals.get(info.get("category"))
            festival = by_id.get(festival_id) if festival_id else None
            if festival and festival.get("published", True):
                pages[url] = {"result": "records", "records": [festival_id], "aliases": [festival["alias"]]}
            else:
                pages[url] = {
                    "result": "skip",
                    "reason": "Рубрика не стала отдельным выпуском. Её материалы учтены по своим адресам.",
                    "records": [],
                }
            continue
        if url == "/rating.html":
            pages[url] = {
                "result": "skip",
                "reason": "Таблица рейтинга разобрана по карточкам дегустаций. Общий адрес без перенаправления, как в пилоте.",
                "records": [],
            }
            continue
        if url in {"/contacts.html", "/inter_tabac_2010.html"}:
            pages[url] = {
                "result": "skip",
                "reason": "Страница контактов или отдельный исторический адрес. Персональные данные в перенос не входят.",
                "records": [],
            }
            continue
        pages[url] = {
            "result": "skip",
            "reason": "Список раздела. Уникальные материалы учтены по item_id, общий адрес не перенаправляется.",
            "records": [],
        }
    return pages


def _file_outcomes(media):
    assets = (media or {}).get("assets") or {}
    attachments = (media or {}).get("attachments") or {}
    missing = (media or {}).get("missing") or {}
    files = {}
    for url, asset in {**assets, **attachments}.items():
        files[url] = {"result": "stored", "sha256": asset.get("sha256"), "bytes": asset.get("bytes")}
    for url, reason in missing.items():
        files[url] = {"result": "missing", "reason": reason}
    return files
