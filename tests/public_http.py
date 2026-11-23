"""Check the seeded public site with the Python standard library."""

import http.client
from html.parser import HTMLParser
import os
from urllib.parse import urlparse
from xml.etree import ElementTree


base = urlparse(os.environ.get("CLUB_URL", "http://localhost:8093"))


def get(path, method="GET"):
    connection = http.client.HTTPConnection(base.hostname, base.port, timeout=10)
    try:
        connection.request(method, path)
        response = connection.getresponse()
        return response.status, response.getheader("Location"), response.read()
    finally:
        connection.close()


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attributes):
        if tag == "a":
            self.urls.append(dict(attributes).get("href", ""))


for path, links in {
    "/": ["/club", "/en/club", "/events/world", "/privacy"],
    "/en/club": ["/club", "/en/contacts"],
    "/en/contacts": ["/contacts", "/en/club"],
    "/events/demo-club-evening": ["/tastings/demo-session", "/albums/demo-evening"],
    "/cigars/demo-edition": ["/tastings/demo-session", "/journal/demo-tea"],
    "/festivals/demo-edition": ["/events/demo-club-evening", "/albums/demo-evening"],
    "/rating": ["/cigars/demo-edition", "/tastings/demo-session"],
    "/journal": ["/journal/rubric/pairing_tea", "/cigars/pairings"],
    "/cigars/pairings": ["/journal/rubric/pairing_tea"],
    "/journal/rubric/pairing_tea": ["/journal/demo-tea"],
}.items():
    status, _, body = get(path)
    assert status == 200, (path, status)
    document = Links()
    document.feed(body.decode())
    for expected in links:
        assert expected in document.urls, (path, expected)

for path, expected in {"/en": "/en/club", "/en/rating?page=1": "/rating?page=1", "/en/membership": "/membership"}.items():
    for method in ("GET", "HEAD"):
        status, location, _ = get(path, method)
        assert status == 302 and location == expected, (method, path, status, location)

status, _, sitemap = get("/sitemap.xml")
assert status == 200
root = ElementTree.fromstring(sitemap)
locations = [urlparse(tag.text).path for tag in root.findall(".//{*}loc")]
alternates = [urlparse(tag.attrib["href"]).path for tag in root.findall(".//{*}link")]
for path in ("/en/club", "/en/contacts"):
    assert path in locations and path in alternates, path
for path in ("/en", "/en/", "/en/events", "/en/rating", "/en/cigars/pairings"):
    assert path not in locations and path not in alternates, path
print("Public pages, linked editorial records, language redirects and sitemap passed.")
