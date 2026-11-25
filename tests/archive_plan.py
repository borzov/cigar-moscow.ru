"""Planner: one page, one result, pilot identities stay put."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "archive"))

from planner import build_plan, names_compatible, redact_sensitive  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PILOT = json.loads((ROOT / "scripts" / "archive" / "pilot.json").read_text(encoding="utf-8"))
OMITTED = {"92": "Таблица привязывает Cazadores к обзору Wide Churchills."}


def article(item, title, body, date="2019-05-01"):
    return {
        "title": title,
        "date": date,
        "url": f"https://www.cigar-moscow.ru/tasting.html?item_id={item}",
        "body": body,
        "images": [f"https://www.cigar-moscow.ru/content/Image/{item}.jpg"],
        "preview": None,
    }


def registry_for(items):
    pages = {"/tasting.html": {"kind": "listing", "section": "tasting"}}
    stored = {}
    for item in items:
        stored[str(item["item_id"])] = item
        for url in item["urls"]:
            pages[url] = {"kind": "article", "item_id": item["item_id"]}
    return {"items": stored, "pages": pages, "categories": {}}


def test_redaction_removes_contact_and_keeps_the_story():
    html = "<p>Встреча прошла в клубе.</p><p>Пишите me@example.com или +7 916 000-00-00, либо +7-925-890-82-21.</p>"
    cleaned, notes = redact_sensitive(html)
    assert notes == 1
    assert "example.com" not in cleaned
    assert "916" not in cleaned
    assert "925" not in cleaned
    assert "Встреча прошла в клубе" in cleaned
    illustrated = '<p><img src="https://www.cigar-moscow.ru/content/Image/454869974594275.jpg"></p><p>Карта 4276 1234 5678 9012.</p>'
    cleaned, notes = redact_sensitive(illustrated)
    assert "454869974594275" in cleaned
    assert "4276" not in cleaned


def test_name_match_accepts_a_line_and_rejects_a_foreign_vitola():
    siblings = ["Macanudo 1968 Corona", "Macanudo 1968 Robusto"]
    assert names_compatible("Macanudo 1968 Gigante", "Три витолы Macanudo 1968", siblings)
    assert not names_compatible(
        "Romeo y Julieta Cazadores",
        "Romeo y Julieta Wide Churchills",
        ["Romeo y Julieta Wide Churchills"],
    )


def test_plan_preserves_pilot_and_describes_every_new_page():
    items = [
        {
            "item_id": 886,
            "section": "cigar_news",
            "title": "Русский вечер",
            "date": "2016-10-15",
            "urls": ["/cigar_news.html?item_id=886"],
            "categories": ["27"],
            "scripts": ["cigar_news"],
        },
        {
            "item_id": 500,
            "section": "tasting",
            "title": "Cohiba Behike BHK 562018-03-02",
            "date": "2018-03-02",
            "urls": ["/tasting.html?item_id=500"],
            "categories": [],
            "scripts": ["tasting"],
        },
    ]
    articles = {
        "500": article(500, "Cohiba Behike BHK 56", "<p>18 марта 2018 года оценка вечера 91 балл.</p>"),
    }
    rating = [{
        "rank": "3",
        "cigar": "Cohiba Behike BHK 56",
        "country": "Куба",
        "collective": [{"score": "91", "href": "/tasting.html?item_id=500"}],
        "individual": [],
    }, {
        "rank": "4",
        "cigar": "Cohiba Behike BHK 56",
        "country": "Куба",
        "collective": [{"score": "95/89", "href": "/tasting.html?item_id=500"}],
        "individual": [],
    }]
    plan = build_plan(registry_for(items), articles, rating, PILOT, OMITTED, {})
    ids = [row["id"] for row in plan["records"]]
    assert ids.count("legacy:article-886") == 1
    assert "legacy:journal:886" not in ids
    assert "legacy:journal:500" in ids
    tasting = next(row for row in plan["records"] if row["id"] == "legacy:tasting:500:3")
    assert tasting["fields"]["field_club_score"] == 91
    assert tasting["fields"]["field_date"] == "2018-03-18"
    ambiguous = next(row for row in plan["records"] if row["id"] == "legacy:tasting:500:4")
    assert "field_club_score" not in ambiguous["fields"]
    assert "95/89" in ambiguous["fields"]["field_score_original"]
    journal = next(row for row in plan["records"] if row["id"] == "legacy:journal:500")
    assert journal["published"] is True
    event = next(row for row in plan["records"] if row["id"] == "legacy:event:500")
    assert event["title"] == "Cohiba Behike BHK 56"
    assert ids.index("legacy:cigar:cohiba-behike-bhk-56") < ids.index(tasting["id"])
    page = plan["outcomes"]["pages"]["/tasting.html?item_id=500"]
    assert page["result"] == "records"
    assert "legacy:journal:500" in page["records"]
    pilot_page = plan["outcomes"]["pages"]["/cigar_news.html?item_id=886"]
    assert "legacy:article-886" in pilot_page["records"]
    assert any("95/89" in question["question"] for question in plan["questions"])
    second = build_plan(registry_for(items), articles, rating, PILOT, OMITTED, {})
    assert second["records"] == plan["records"]


def test_rating_on_a_news_page_still_has_an_event():
    item = {
        "item_id": 501,
        "section": "cigar_news",
        "title": "Partagas Serie D No 4",
        "date": "2018-04-01",
        "urls": ["/cigar_news.html?item_id=501"],
        "categories": [],
        "scripts": ["cigar_news"],
    }
    articles = {"501": article(501, "Partagas Serie D No 4", "<p>Оценка вечера.</p>", "2018-04-01")}
    rating = [{
        "rank": "8",
        "cigar": "Partagas Serie D No 4",
        "country": "Куба",
        "collective": [{"score": "90", "href": "/cigar_news.html?item_id=501"}],
        "individual": [],
    }]
    plan = build_plan(registry_for([item]), articles, rating, [], {}, {})
    tasting = next(row for row in plan["records"] if row["id"] == "legacy:tasting:501:8")
    assert tasting["fields"]["field_event"]["ref"] == "legacy:event:501"
    assert any(row["id"] == "legacy:event:501" for row in plan["records"])


def test_already_redacted_text_still_asks_the_editor():
    item = {
        "item_id": 78,
        "section": "cigar_news",
        "title": "Заметка",
        "date": "2016-09-02",
        "urls": ["/cigar_news.html?item_id=78"],
        "categories": [],
        "scripts": ["cigar_news"],
    }
    articles = {"78": article(78, "Заметка", "<p>Пишите [данные удалены].</p>", "2016-09-02")}
    plan = build_plan(registry_for([item]), articles, [], [], {}, {})
    question = next(item for item in plan["questions"] if item["id"] == "redacted-78")
    assert "телефон" in question["question"]


def test_spirit_essay_and_named_report_keep_their_own_addresses():
    spirit = {
        "item_id": 194,
        "section": "spirit",
        "title": "Чьи шишки в лесу.",
        "date": "2011-01-31",
        "urls": ["/cigar_news.html?item_id=194"],
        "categories": [],
        "scripts": ["cigar_news"],
    }
    registry = registry_for([spirit])
    registry["documents"] = {
        "page-del-habano-1": {
            "item_id": "page-del-habano-1",
            "section": "cigar_news",
            "title": "День первый",
            "date": "2010-02-19",
            "urls": ["/del_habano_1.html"],
            "categories": [],
            "source": "/del_habano_1.html",
        }
    }
    registry["pages"]["/del_habano_1.html"] = {"kind": "document", "item_id": "page-del-habano-1"}
    images = [f"https://www.cigar-moscow.ru/content/Image/habano/{index}.jpg" for index in range(8)]
    articles = {
        "194": article(194, "Чьи шишки в лесу.", "<p>Текст очерка.</p>", "2011-01-31"),
        "page-del-habano-1": {
            "title": "День первый",
            "date": "2010-02-19",
            "url": "https://www.cigar-moscow.ru/del_habano_1.html",
            "body": "<p>До фестиваля осталось три дня.</p>",
            "images": images,
            "preview": None,
        },
    }
    plan = build_plan(registry, articles, [], [], {}, {})
    essay = next(row for row in plan["records"] if row["id"] == "legacy:journal:194")
    assert essay["fields"]["field_rubrics"] == [{"slug": "club"}]
    assert essay["redirects"] == ["/cigar_news.html?item_id=194"]
    report = next(row for row in plan["records"] if row["id"] == "legacy:journal:page-del-habano-1")
    assert report["alias"] == "/journal/page-del-habano-1"
    assert report["article"] == "page-del-habano-1"
    assert report["redirects"] == ["/del_habano_1.html"]
    assert report["source"] == "/del_habano_1.html"
    album = next(row for row in plan["records"] if row["id"] == "legacy:album:page-del-habano-1")
    assert album["images_from"] == ["page-del-habano-1"]
    assert plan["outcomes"]["pages"]["/del_habano_1.html"]["result"] == "records"
    loose = {
        "item_id": "file-report-2017",
        "section": "cigar_news",
        "title": "Отчёт",
        "date": "2017-06-13",
        "urls": [],
        "source": "/content/Image/news/2017-06-13/report.docx",
        "categories": [],
    }
    registry["documents"]["file-report-2017"] = loose
    articles["file-report-2017"] = {
        "title": "Отчёт",
        "date": "2017-06-13",
        "url": "https://www.cigar-moscow.ru/content/Image/news/2017-06-13/report.docx",
        "body": '<p><a href="https://www.cigar-moscow.ru/content/Image/news/2017-06-13/report.docx">report.docx</a></p>',
        "images": [],
        "preview": None,
    }
    plan = build_plan(registry, articles, [], [], {}, {})
    attachment = next(row for row in plan["records"] if row["id"] == "legacy:journal:file-report-2017")
    assert "redirects" not in attachment
    assert attachment["source"] == "/content/Image/news/2017-06-13/report.docx"


def test_price_becomes_a_draft_without_a_redirect():
    item = {
        "item_id": 77,
        "section": "anons",
        "title": "Пакет участия",
        "date": "2016-09-01",
        "urls": ["/anons.html?item_id=77"],
        "categories": [],
        "scripts": ["anons"],
    }
    body = "<p>Стоимость пакета 120 000 руб. Звоните +7 903 111-22-33.</p><p>Программа вечера.</p>"
    articles = {"77": article(77, "Пакет участия", body, "2016-09-01")}
    articles["77"]["url"] = "https://www.cigar-moscow.ru/anons.html?item_id=77"
    plan = build_plan(registry_for([item]), articles, [], [], {}, {})
    journal = next(row for row in plan["records"] if row["type"] == "journal")
    assert journal["published"] is False
    assert "redirects" not in journal
    assert "903" not in json.dumps(plan["questions"], ensure_ascii=False)
    assert plan["outcomes"]["pages"]["/anons.html?item_id=77"]["result"] == "draft"


if __name__ == "__main__":
    test_redaction_removes_contact_and_keeps_the_story()
    test_name_match_accepts_a_line_and_rejects_a_foreign_vitola()
    test_plan_preserves_pilot_and_describes_every_new_page()
    test_rating_on_a_news_page_still_has_an_event()
    test_already_redacted_text_still_asks_the_editor()
    test_spirit_essay_and_named_report_keep_their_own_addresses()
    test_price_becomes_a_draft_without_a_redirect()
    print("planner passed")
