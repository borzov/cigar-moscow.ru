"""Listing pages: pagination, duplicates, Windows-1251 titles."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "archive"))

from listing import add_listing, normalize, parse_listing  # noqa: E402


PAGE = """
<div class="mainItemCell">
  <div class="newsItem">
    <div class="imgPrev"><a href="cigar_news.html?item_id=10&amp;utm_source=mail"><img src="a.jpg"></a></div>
    <div class="header"><span class="headerTxt">Первая новость <span class="date">// 2020-01-02</span></span></div>
  </div>
  <div class="newsSmall">
    <div class="imgPrev"><a href="tasting.html?item_id=10"><img src="b.jpg"></a></div>
    <div class="header"><span class="headerTxt"><a href="tasting.html?item_id=10">Та же запись</a> <span class="date">// 2020-01-02</span></span></div>
  </div>
  <div class="newsSmall">
    <div class="imgPrev"><a href="tasting.html?item_id=11"><img src="c.jpg"></a></div>
    <div class="header"><span class="headerTxt">Дегустация <span class="date">// 2019-05-01</span></span></div>
  </div>
  <a href="cigar_news.html?show_all=0&amp;from=5">2</a>
  <a href="news.html?category=45">MA Cigar Fest 2021</a>
</div>
<div class="anons_item">
  <div class="imgPrev"><a href="anons.html?item_id=1086"><img src="content/Image/news/1086.jpg"></a></div>
  <div class="header"><span class="headerTxt">Вечер памяти Дона Алехандро</span></div>
  <div class="newsLink"><a href="anons.html?item_id=1086">Читать далее..</a></div>
</div>
""".encode("cp1251")


def test_normalize_keeps_item_and_drops_tracker():
    assert normalize("/Cigar_News.html?utm_source=x&item_id=10") == "/cigar_news.html?item_id=10"


def test_parse_merges_duplicate_item_and_reads_cyrillic():
    parsed = parse_listing(PAGE, "https://www.cigar-moscow.ru/cigar_news.html?show_all=1")
    registry = {"items": {}, "pages": {}, "categories": {}}
    add_listing(registry, parsed, category_id=None)
    assert set(registry["items"]) == {"10", "11", "1086"}
    first = registry["items"]["10"]
    assert first["title"] == "Первая новость"
    assert "/cigar_news.html?item_id=10" in first["urls"]
    assert "/tasting.html?item_id=10" in first["urls"]
    assert first["date"] == "2020-01-02"
    assert any("from=5" in page for page in registry["pages"])
    assert registry["categories"]["45"]["title"] == "MA Cigar Fest 2021"
    announcement = registry["items"]["1086"]
    assert announcement["title"] == "Вечер памяти Дона Алехандро"
    assert announcement["section"] == "anons"
    assert announcement["urls"] == ["/anons.html?item_id=1086"]


if __name__ == "__main__":
    test_normalize_keeps_item_and_drops_tracker()
    test_parse_merges_duplicate_item_and_reads_cyrillic()
    print("listing parser passed")
