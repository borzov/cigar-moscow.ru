#!/usr/bin/env python3
"""Inventory, preview, import and verify the club archive. Raw snapshots stay outside Git."""

import argparse
import os
from pathlib import Path
import subprocess
import sys
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parent))

from snapshot import Limiter, fetch_articles, inventory, preview, read_json  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
DEFAULT_DEST = Path.home() / ".local/share/cigar-moscow" / "archive"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("inventory", "fetch", "preview", "import", "resume", "verify"))
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    parser.add_argument("--limit", type=int, default=0, help="Import or fetch only the first N materials. 0 means all.")
    parser.add_argument("--compose-project", default=os.environ.get("COMPOSE_PROJECT_NAME", ""))
    parser.add_argument("--http", default="", help="Base URL for the representative HTTP checks, for example http://localhost:18096")
    args = parser.parse_args()
    limiter = Limiter()
    os.chdir(REPO)
    if args.command == "inventory":
        inventory(args.dest, limiter)
    elif args.command == "fetch":
        fetch_articles(args.dest, limiter, args.limit)
    elif args.command == "preview":
        preview(args.dest)
    elif args.command == "import":
        import_archive(args.dest, args.compose_project)
    elif args.command == "resume":
        if not (args.dest / "registry.json").exists():
            inventory(args.dest, limiter)
        fetch_articles(args.dest, limiter, args.limit)
        preview(args.dest)
        import_archive(args.dest, args.compose_project)
    elif args.command == "verify":
        verify(args.dest, args.compose_project, args.http)
    return 0


def compose(project, *command):
    env = os.environ.copy()
    if project:
        env["COMPOSE_PROJECT_NAME"] = project
    completed = subprocess.run(["docker", "compose", *command], cwd=REPO, env=env)
    if completed.returncode != 0:
        raise RuntimeError(f"docker compose failed: {' '.join(command)}")


def import_archive(root, project):
    names = [
        "articles", "assets", "attachments", "assets.json", "attachments.json",
        "extraction-report.json", "inventory.json", "plan",
    ]
    present = [name for name in names if (root / name).exists()]
    compose(project, "exec", "-T", "web", "install", "-d", "-m", "0700", "/opt/drupal/private/archive")
    tar_env = os.environ.copy()
    tar_env["COPYFILE_DISABLE"] = "1"
    tar = subprocess.Popen(["tar", "-C", str(root), "-cf", "-", *present], stdout=subprocess.PIPE, env=tar_env)
    env = os.environ.copy()
    if project:
        env["COMPOSE_PROJECT_NAME"] = project
    load = subprocess.run(
        ["docker", "compose", "exec", "-T", "web", "tar", "xf", "-", "-C", "/opt/drupal/private/archive"],
        cwd=REPO, env=env, stdin=tar.stdout,
    )
    tar.stdout.close()
    tar.wait()
    if tar.returncode != 0 or load.returncode != 0:
        raise RuntimeError("Could not copy the snapshot into Drupal.")
    compose(
        project, "exec", "-T",
        "-e", "CLUB_ARCHIVE_DIR=/opt/drupal/private/archive",
        "-e", "CLUB_ARCHIVE_PLAN=/opt/drupal/private/archive/plan/records.json",
        "-e", "CLUB_ARCHIVE_INVENTORY=/opt/drupal/private/archive/inventory.json",
        "-e", "CLUB_ARCHIVE_ACCEPT_404=1",
        "-e", "CLUB_ARCHIVE_COMMIT=record",
        "web", "php", "-d", "memory_limit=2048M",
        "vendor/drush/drush/drush.php", "php:script", "/opt/drupal/scripts/archive/import.php",
    )


def verify(root, project, http_base):
    registry = read_json(root / "registry.json")
    outcomes = read_json(root / "plan" / "outcomes.json")
    records = read_json(root / "plan" / "records.json")
    missing_pages = sorted(set(registry["pages"]) - set(outcomes["pages"]))
    if missing_pages:
        raise RuntimeError(f"{len(missing_pages)} pages have no result")
    assets = read_json(root / "assets.json") if (root / "assets.json").exists() else {}
    attachments = read_json(root / "attachments.json") if (root / "attachments.json").exists() else {}
    failed = read_json(root / "extraction-report.json").get("failed_media", {})
    files = outcomes["files"]
    for url in [*assets, *attachments, *failed]:
        if url not in files:
            raise RuntimeError(f"File has no result: {url}")
    print(f"Ledger covers {len(outcomes['pages'])} pages and {len(files)} files.")
    compose(
        project, "exec", "-T",
        "-e", "CLUB_ARCHIVE_DIR=/opt/drupal/private/archive",
        "-e", "CLUB_ARCHIVE_PLAN=/opt/drupal/private/archive/plan/records.json",
        "web", "php", "-d", "memory_limit=2048M",
        "vendor/drush/drush/drush.php", "php:script", "/opt/drupal/tests/archive_import.php",
    )
    if http_base:
        check_http(http_base.rstrip("/"), records)
    print("Verification passed.")


def check_http(base, records):
    published = next(row for row in records if row["type"] == "journal" and row.get("published", True) and row.get("redirects"))
    draft = next(row for row in records if row["type"] == "journal" and row.get("published") is False)
    status, body, _location, content_type = request(base + published["alias"])
    if status != 200:
        raise RuntimeError(f"Published journal {published['alias']} returned {status}")
    image = _first_image(body)
    if image:
        image_url = image if image.startswith("http") else base + image
        image_status, _image_body, _image_location, image_type = request(image_url)
        if image_status != 200 or not (image_type or "").startswith("image/"):
            raise RuntimeError(f"Photograph {image_url} returned {image_status} {image_type}")
    status, _body, location, _content_type = request(base + published["redirects"][0])
    if status != 301 or not location or not str(location).endswith(published["alias"]):
        raise RuntimeError(f"Legacy URL {published['redirects'][0]} returned {status} {location}")
    status, _body, _location, _content_type = request(base + draft["alias"])
    if status == 200:
        raise RuntimeError(f"Draft is public: {draft['alias']}")
    if draft.get("source"):
        status, _body, _location, _content_type = request(base + draft["source"])
        if status != 404:
            raise RuntimeError(f"Draft legacy URL {draft['source']} returned {status}")
    status, _body, _location, _content_type = request(base + "/rating.html")
    if status != 404:
        raise RuntimeError(f"Rating index returned {status}")
    print(f"HTTP checks passed for {published['alias']} and draft {draft['alias']}.")


def _first_image(body):
    for part in body.split('src="')[1:]:
        url = part.split('"', 1)[0]
        if "/sites/" in url or url.startswith("http"):
            return url
    return ""


class _Stay(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(url):
    opener = build_opener(_Stay)
    try:
        with opener.open(Request(url, headers={"User-Agent": "MA-Archive-Verify/1.0"}), timeout=30) as response:
            return response.status, response.read(100000).decode("utf-8", "replace"), response.headers.get("Location"), response.headers.get("Content-Type", "")
    except HTTPError as error:
        return error.code, error.read(2000).decode("utf-8", "replace"), error.headers.get("Location"), error.headers.get("Content-Type", "")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as error:
        print(error, file=sys.stderr)
        raise SystemExit(1)
