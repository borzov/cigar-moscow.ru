"""Article extraction keeps a page when the old markup is slightly irregular."""

import sys
from pathlib import Path

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "archive"))

from fetch import extract, extract_document, request_url  # noqa: E402


def document(body):
    html = f"""
    <div class="mainItemCell"><div class="newsItem">
      <div class="header"><span class="headerTxt">{body[0]}</span></div>
      <div class="imgPrev"><img src="content/Image/news/1.jpg" alt=""></div>
      <div class="Txt">{body[1]}<div class="category">раздел</div></div>
    </div></div>
    """
    return BeautifulSoup(html, "html5lib")


def test_missing_title_gets_a_service_name():
    doc = document(('<span class="date">// 2011-07-16</span>', "<p>Текст без заголовка.</p>"))
    record, _alts, _pdfs, _metrics = extract(
        doc, "https://www.cigar-moscow.ru/okurok.html?item_id=336", 336,
        allow_empty=True, strict_template=False,
    )
    assert record["title"] == "Материал 336"
    assert record["warnings"] == ["У страницы нет заголовка. Поставлено служебное название."]
    assert record["date"] == "2011-07-16"
    assert "Текст без заголовка." in record["body"]


def test_punctuation_split_by_a_tag_is_kept():
    doc = document((
        'Ежегодная дегустация <span class="date">// 2011-08-25</span>',
        '<p>Пишите <a href="mailto:baltchug@advantageaustria.ru">baltchug@advantageaustria.ru</a>, дальше.</p>',
    ))
    record, _alts, _pdfs, _metrics = extract(
        doc, "https://www.cigar-moscow.ru/cigar_news.html?item_id=368", 368,
        allow_empty=True, strict_template=False,
    )
    assert "baltchug@advantageaustria.ru" in record["body"]
    assert "дальше" in record["body"]


def test_named_report_keeps_the_story_and_drops_the_site_badge():
    html = """
    <div class="mainItemCell">
      <div class="pageMainHeader"><h1>День первый</h1></div>
      <p>До фестиваля осталось три дня.</p>
      <p><img src="content/Image/maf20.gif" alt=""></p>
      <div style="display: none"><a href="content/Image/habano/2010-02-19/horz/a.jpg" rel="group1">Перейти к галерее</a></div>
      <div class="toTop">Перейти наверх</div>
    </div>
    """
    record, _alts, _pdfs, _metrics = extract_document(
        BeautifulSoup(html, "html5lib"),
        "https://www.cigar-moscow.ru/del_habano_1.html",
        "page-del-habano-1",
    )
    assert record["title"] == "День первый"
    assert "До фестиваля осталось три дня." in record["body"]
    assert "maf20.gif" not in record["body"]
    assert "Перейти наверх" not in record["body"]
    assert "Перейти к галерее" not in record["body"]
    assert record["images"] == ["https://www.cigar-moscow.ru/content/Image/habano/2010-02-19/horz/a.jpg"]


def test_request_url_encodes_spaces_and_keeps_plain_urls():
    encoded = request_url("https://www.cigar-moscow.ru/content/WhatsApp Image 2020.jpeg")
    assert " " not in encoded
    assert encoded == "https://www.cigar-moscow.ru/content/WhatsApp%20Image%202020.jpeg"
    assert request_url("https://www.cigar-moscow.ru/cigar_news.html?item_id=10") == "https://www.cigar-moscow.ru/cigar_news.html?item_id=10"


if __name__ == "__main__":
    test_missing_title_gets_a_service_name()
    test_punctuation_split_by_a_tag_is_kept()
    test_named_report_keeps_the_story_and_drops_the_site_badge()
    test_request_url_encodes_spaces_and_keeps_plain_urls()
    print("extract passed")
