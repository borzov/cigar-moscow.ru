#!/usr/bin/env python3
"""Check the pilot's editorial decisions against the offline archive snapshot."""

import argparse
import json
import re
from html import unescape
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

BASE = Path(__file__).resolve().parent


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def plain(fragment):
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def require(condition, message):
    if not condition:
        raise ValueError(message)


def score_links(cell):
    # Each score is an anchor, including both links inside rank 69's one cell.
    links = re.findall(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', cell, re.I | re.S)
    return [{"score": plain(label), "href": unescape(href)} for href, label in links]


def check_rating(snapshot, wanted):
    legacy = (snapshot / "originals" / "rating.html").read_bytes().decode("cp1251")
    found = set()
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", legacy, re.I | re.S):
        cells = re.findall(r"<td\b[^>]*>(.*?)</td>", row, re.I | re.S)
        if len(cells) != 5 or plain(cells[0]) not in wanted:
            continue
        rank = plain(cells[0])
        observed = {
            "cigar": plain(cells[1]),
            "country": plain(cells[2]),
            "collective": score_links(cells[3]),
            "individual": score_links(cells[4]),
        }
        require(rank not in found and observed == wanted[rank], f"Rating row {rank} changed")
        found.add(rank)
    require(found == set(wanted), "A reviewed rating row is missing")


def verify(snapshot):
    records = read_json(BASE / "pilot.json")
    evidence = read_json(BASE / "pilot-evidence.json")
    check_rating(snapshot, evidence["rating_rows"])
    articles = {}
    for item, expected in evidence["articles"].items():
        source = read_json(snapshot / "articles" / f"{item}.json")
        article = next(r for r in records if r.get("article") == int(item))
        require(urlsplit(source["url"]).path + "?" + urlsplit(source["url"]).query == article["source"],
                f"Wrong archive path for article {item}")
        require(source["date"] == expected["published_in_archive"], f"Publication date for article {item}")
        articles[int(item)] = plain(source["body"])
        for anchor in expected["anchors"]:
            require(anchor in articles[int(item)], f"Evidence changed in article {item}: {anchor}")

    ids = {r["id"]: r for r in records}
    tasting_ids = {r["id"] for r in records if r["type"] == "tasting"}
    require(tasting_ids == set(evidence["observations"]), "Incomplete tasting evidence")
    for key, decision in evidence["observations"].items():
        row = ids[key]
        fields = row["fields"]
        number = decision["article"]
        require(row["created"] == evidence["articles"][str(number)]["published_in_archive"],
                f"Publication vs tasting date for {key}")
        require(fields["field_date"] == decision["tasted"], f"Wrong tasting date for {key}")
        require(fields.get("field_club_score") == decision["collective"]
                and fields.get("field_individual_score") == decision["individual"]
                and fields["field_score_original"] == decision["original"], f"Wrong score for {key}")
        rank = evidence["rating_rows"][str(decision["rank"])]
        links = rank["collective"] + rank["individual"]
        require(any(parse_qs(urlsplit(link["href"]).query)["item_id"] == [str(number)]
                    and link["score"] == decision["original"] for link in links), f"Wrong score link for {key}")
        body = articles[number]
        start = body.index(decision["source_scope"])
        end = body.index(decision["until"], start) if decision["until"] else len(body)
        require(decision["score_evidence"] in body[start:end], f"Wrong source card for {key}")

    require(len(ids) == len(records), "Duplicate source identity")
    require(len({r["alias"] for r in records}) == len(records), "Duplicate canonical address")
    for row in records:
        require(row.get("published", True) or not row.get("redirects"), f"Draft redirect for {row['id']}")
    print(f"Verified {len(evidence['rating_rows'])} original rating rows, "
          f"{len(articles)} archive reports and {len(tasting_ids)} dated tastings.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path, help="Directory written by fetch.py")
    verify(parser.parse_args().snapshot)
