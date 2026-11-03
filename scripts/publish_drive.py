#!/usr/bin/env python3
"""Put a finished episode on Google Drive in the house layout, ready to post.

    python scripts/publish_drive.py publish/heated-floor.json      # build or refresh the folder
    python scripts/publish_drive.py auth                           # once, on YOUR computer

Layout, under the parent folder named in the spec (Mike Hewitt by default):

    [Episode working name, e.g. Heated Floor]/
        Long Video (Manual Upload)/        the intro and the text touches package, the
                                           finished long video goes here by hand
        Long Video Title and Description   Google Doc, stage 2
        [slug]-long-thumbnail.jpg          stage 2
        Short/
            [slug]-short.mp4
            [slug]-short-thumbnail.jpg
            Short Title and Description    Google Doc

Rerunning is safe: folders and docs are found by name and reused, a doc is
rewritten in place, and a file already in its folder with the same name and
size is skipped.

Credentials come from the environment or a gitignored .env, never a committed
file: GOOGLE_DRIVE_CLIENT_ID, GOOGLE_DRIVE_CLIENT_SECRET, GOOGLE_DRIVE_REFRESH_TOKEN.
`auth` prints the refresh token. It opens a browser, so run it on your own
computer, not in a cloud session.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
import urllib.parse
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/drive/v3/files"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
FOLDER = "application/vnd.google-apps.folder"
DOC = "application/vnd.google-apps.document"
SCOPE = "https://www.googleapis.com/auth/drive"
DEFAULT_PARENT = "1ouQYxq3BO-bshx7H5a-VUL9QzPL_ulGj"   # Mike Hewitt
CHUNK = 8 * 1024 * 1024


def load_dotenv() -> None:
    env = REPO_ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        key, _, value = line.strip().partition("=")
        if key and not key.startswith("#") and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


def need(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"{name} is not set. See the youtube-publish-package skill, setup section.")
    return value


class Drive:
    def __init__(self) -> None:
        response = requests.post(TOKEN_URL, data={
            "client_id": need("GOOGLE_DRIVE_CLIENT_ID"),
            "client_secret": need("GOOGLE_DRIVE_CLIENT_SECRET"),
            "refresh_token": need("GOOGLE_DRIVE_REFRESH_TOKEN"),
            "grant_type": "refresh_token"}, timeout=30)
        if response.status_code != 200:
            sys.exit("Google refused the refresh token: " + response.text[:300] + "\n"
                     "If it says invalid_grant, the OAuth app is still in Testing, which "
                     "expires tokens after 7 days. Publish it to In production and run auth again.")
        self.session = requests.Session()
        self.session.headers["Authorization"] = "Bearer " + response.json()["access_token"]

    def find(self, parent: str, name: str, mime: str | None = None) -> dict | None:
        query = f"'{parent}' in parents and name = '{name.replace(chr(39), chr(92) + chr(39))}' and trashed = false"
        if mime:
            query += f" and mimeType = '{mime}'"
        response = self.session.get(API, params={"q": query, "fields": "files(id,name,size,mimeType)",
                                                 "supportsAllDrives": "true",
                                                 "includeItemsFromAllDrives": "true"}, timeout=30)
        response.raise_for_status()
        files = response.json()["files"]
        return files[0] if files else None

    def folder(self, parent: str, name: str) -> str:
        found = self.find(parent, name, FOLDER)
        if found:
            print(f"  have folder  {name}")
            return found["id"]
        response = self.session.post(API, params={"supportsAllDrives": "true"},
                                     json={"name": name, "mimeType": FOLDER, "parents": [parent]},
                                     timeout=30)
        response.raise_for_status()
        print(f"  made folder  {name}")
        return response.json()["id"]

    def doc(self, parent: str, name: str, body_html: str) -> str:
        found = self.find(parent, name, DOC)
        boundary = "remodelking"
        meta = {"name": name} if found else {"name": name, "mimeType": DOC, "parents": [parent]}
        payload = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
                   f"{json.dumps(meta)}\r\n--{boundary}\r\nContent-Type: text/html; charset=UTF-8\r\n\r\n"
                   f"{body_html}\r\n--{boundary}--").encode()
        headers = {"Content-Type": f"multipart/related; boundary={boundary}"}
        params = {"uploadType": "multipart", "supportsAllDrives": "true"}
        if found:
            response = self.session.patch(f"{UPLOAD}/{found['id']}", params=params,
                                          data=payload, headers=headers, timeout=60)
        else:
            response = self.session.post(UPLOAD, params=params, data=payload,
                                         headers=headers, timeout=60)
        response.raise_for_status()
        print(f"  {'rewrote' if found else 'made'} doc     {name}")
        return response.json()["id"]

    def upload(self, parent: str, path: Path, name: str | None = None) -> str:
        name = name or path.name
        size = path.stat().st_size
        found = self.find(parent, name)
        if found and int(found.get("size", -1)) == size:
            print(f"  have file    {name}")
            return found["id"]
        mime = {".mp4": "video/mp4", ".mov": "video/quicktime", ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg", ".png": "image/png", ".zip": "application/zip",
                ".pdf": "application/pdf"}.get(path.suffix.lower(), "application/octet-stream")
        params = {"uploadType": "resumable", "supportsAllDrives": "true"}
        headers = {"X-Upload-Content-Type": mime, "X-Upload-Content-Length": str(size)}
        if found:
            start = self.session.patch(f"{UPLOAD}/{found['id']}", params=params, json={},
                                       headers=headers, timeout=30)
        else:
            start = self.session.post(UPLOAD, params=params, headers=headers, timeout=30,
                                      json={"name": name, "parents": [parent]})
        start.raise_for_status()
        location = start.headers["Location"]
        sent = 0
        with path.open("rb") as handle:
            while sent < size:
                chunk = handle.read(CHUNK)
                end = sent + len(chunk) - 1
                response = self.session.put(location, data=chunk, timeout=300, headers={
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {sent}-{end}/{size}"})
                if response.status_code not in (200, 201, 308):
                    response.raise_for_status()
                sent = end + 1
                print(f"\r  uploading    {name}  {sent * 100 // size}%", end="", flush=True)
        print()
        return response.json()["id"]


def doc_html(title: str, block: dict) -> str:
    """Title first, alternates under it, then the description exactly as it pastes."""
    parts = [f"<h1>{html.escape(title)}</h1>",
             "<h2>Title</h2>", f"<p>{html.escape(block['title'])}</p>"]
    if block.get("alternates"):
        parts.append("<h3>Alternate titles</h3><ul>"
                     + "".join(f"<li>{html.escape(a)}</li>" for a in block["alternates"]) + "</ul>")
    parts.append("<h2>Description</h2>")
    for paragraph in block["description"].strip().split("\n\n"):
        lines = "<br>".join(html.escape(line) for line in paragraph.split("\n"))
        parts.append(f"<p>{lines}</p>")
    if block.get("notes"):
        parts.append("<h3>Upload notes</h3><ul>"
                     + "".join(f"<li>{html.escape(n)}</li>" for n in block["notes"]) + "</ul>")
    return "<html><body>" + "".join(parts) + "</body></html>"


def package(spec_path: Path) -> None:
    """Stage 1 files the pieces and the Short. Stage 2, once long.title and
    long.description exist (written from the final long video), adds the long
    Doc and the long thumbnail. Whatever the spec carries is filed."""
    spec = json.loads(spec_path.read_text())
    slug = spec["slug"]
    long_, short = spec.get("long", {}), spec["short"]
    paths = [*long_.get("pieces", []), short["video"], short["thumbnail"]]
    if long_.get("thumbnail"):
        paths.append(long_["thumbnail"])
    for path in paths:
        if not (REPO_ROOT / path).exists():
            sys.exit(f"missing {path}, build it before packaging")

    drive = Drive()
    parent = spec.get("parent_folder_id", DEFAULT_PARENT)
    episode = drive.folder(parent, spec["episode"])
    manual = drive.folder(episode, "Long Video (Manual Upload)")
    for piece in long_.get("pieces", []):
        drive.upload(manual, REPO_ROOT / piece)
    if long_.get("title") and long_.get("description"):
        drive.doc(episode, "Long Video Title and Description", doc_html("Long video", long_))
    if long_.get("thumbnail"):
        drive.upload(episode, REPO_ROOT / long_["thumbnail"], f"{slug}-long-thumbnail.jpg")

    short_folder = drive.folder(episode, "Short")
    drive.upload(short_folder, REPO_ROOT / short["video"], f"{slug}-short.mp4")
    drive.upload(short_folder, REPO_ROOT / short["thumbnail"], f"{slug}-short-thumbnail.jpg")
    drive.doc(short_folder, "Short Title and Description", doc_html("Short", short))
    print(f"\nDone: https://drive.google.com/drive/folders/{episode}")


def auth() -> None:
    """Loopback OAuth on your own computer, prints the refresh token once."""
    import http.server
    import secrets
    import webbrowser

    client_id = need("GOOGLE_DRIVE_CLIENT_ID")
    client_secret = need("GOOGLE_DRIVE_CLIENT_SECRET")
    state = secrets.token_urlsafe(16)
    result: dict = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if query.get("state", [""])[0] == state:
                result["code"] = query.get("code", [""])[0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Done. You can close this tab and go back to the terminal.")

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    redirect = f"http://127.0.0.1:{server.server_port}"
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": client_id, "redirect_uri": redirect, "response_type": "code",
        "scope": SCOPE, "access_type": "offline", "prompt": "consent", "state": state})
    print("Opening the Google sign in. If no browser opens, paste this:\n" + url)
    webbrowser.open(url)
    while "code" not in result:
        server.handle_request()
    response = requests.post(TOKEN_URL, data={
        "code": result["code"], "client_id": client_id, "client_secret": client_secret,
        "redirect_uri": redirect, "grant_type": "authorization_code"}, timeout=30)
    response.raise_for_status()
    token = response.json().get("refresh_token")
    if not token:
        sys.exit("Google sent no refresh token. Remove the app's access at "
                 "myaccount.google.com/permissions and run auth again.")
    print("\nGOOGLE_DRIVE_REFRESH_TOKEN=" + token)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("spec", help="publish/[slug].json, or auth")
    args = parser.parse_args()
    load_dotenv()
    if args.spec == "auth":
        auth()
    else:
        package(Path(args.spec))


if __name__ == "__main__":
    main()
