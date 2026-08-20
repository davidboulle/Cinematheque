#!/usr/bin/env python3

import json
import os
import re
import subprocess
import sys
import webbrowser
import hashlib
from collections import defaultdict
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

try:
    from config import (
        MOVIE_ROOTS, IGNORED_FOLDER_NAMES, VIDEO_EXTENSIONS, PORT,
        NOISE_WORDS as _NOISE_WORDS, AUTO_TAG_FROM_FOLDERS, IGNORED_TAG_NAMES,
        CATEGORIES_ROOTS, FFMPEG_PATH, THUMBNAIL_TIMESTAMPS_PERCENT,
    )
except ImportError:
    print("[!] config.py introuvable. Crée-le avec MOVIE_ROOTS = [...]")
    sys.exit(1)

DATA_FILE = Path(__file__).parent / "library.json"
HTML_FILE = Path(__file__).parent / "index.html"
THUMBNAILS_DIR = Path(__file__).parent / "thumbnails"

# ============================================================ #
#                    Méthodes Utilitaires                      #
# ============================================================ #

def load_library():
    if DATA_FILE.exists():
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"movies": {}, "playlists": {}}


def save_library(lib):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(lib, f, ensure_ascii=False, indent=2)


def movie_id(path: str) -> str:
    return hashlib.sha1(path.encode("utf-8")).hexdigest()[:16]


_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


def normalize_title(title: str) -> str:
    t = title.lower()
    t = re.sub(r"[\[\(\{].*?[\]\)\}]", " ", t)
    t = re.sub(r"[._\-]", " ", t)
    for word in _NOISE_WORDS:
        t = re.sub(rf"\b{re.escape(word)}\b", " ", t)
    t = _YEAR_RE.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()


def extract_year(title: str):
    match = _YEAR_RE.search(title)
    return match.group(0) if match else None


def duplicate_key(norm_title: str, year):
    if len(norm_title) < 3:
        return None
    return f"{norm_title}|{year}" if year else norm_title

def extract_tags_from_path(file_path: str, root_path: Path) -> list:
    if not AUTO_TAG_FROM_FOLDERS:
        return []
    try:
        rel_path = Path(file_path).relative_to(root_path)
        parts = rel_path.parts[:-1]
        return [re.sub('_+', ' ', p).strip() for p in parts if p and p.replace('_', '') not in IGNORED_TAG_NAMES]
    except ValueError:
        return []


def build_category_index():
    file_index, folder_index = defaultdict(list), defaultdict(list)
    roots = CATEGORIES_ROOTS if isinstance(CATEGORIES_ROOTS, list) else (
        [CATEGORIES_ROOTS] if CATEGORIES_ROOTS else [])

    for cat_root in [Path(r) for r in roots if Path(r).exists()]:
        for cat_dir in [d for d in cat_root.iterdir() if d.is_dir()]:
            tag = re.sub(r'_+', ' ', cat_dir.name).strip()
            for item in [i for i in cat_dir.iterdir() if i.suffix.lower() == ".lnk"]:
                stem = re.sub(r' - (raccourci|shortcut|lien symbolique)$',
                              '', item.stem, flags=re.I).strip()
                if stem:
                    file_index[stem.lower()].append(tag)
                    folder_index[stem.lower()].append(tag)
    return file_index, folder_index


def scan_movies():
    lib = load_library()
    found_ids, seen_by_dup_key = set(), defaultdict(list)

    for root in MOVIE_ROOTS:
        root_path = Path(root)
        if not root_path.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root_path):
            dirnames[:] = [d for d in dirnames if d.lower()
                           not in IGNORED_FOLDER_NAMES]
            for filename in filenames:
                if Path(filename).suffix.lower() not in VIDEO_EXTENSIONS:
                    continue
                full_path = str(Path(dirpath) / filename)
                mid = movie_id(full_path)
                found_ids.add(mid)

                title = Path(filename).stem
                norm, year = normalize_title(title), extract_year(title)
                dup_key = duplicate_key(norm, year)
                if dup_key:
                    seen_by_dup_key[dup_key].append(mid)

                path_tags = extract_tags_from_path(full_path, root_path)
                if mid in lib["movies"]:
                    lib["movies"][mid].update({"path": full_path, "title": title, "norm_title": norm, "year": year,
                                              "dup_key": dup_key, "size_bytes": os.path.getsize(full_path) if os.path.exists(full_path) else None})
                    for pt in path_tags:
                        if pt not in lib["movies"][mid].get("tags", []):
                            lib["movies"][mid]["tags"].append(pt)
                else:
                    lib["movies"][mid] = {"path": full_path, "title": title, "norm_title": norm, "year": year, "dup_key": dup_key, "size_bytes": os.path.getsize(
                        full_path) if os.path.exists(full_path) else None, "favorite": False, "categories": [], "tags": path_tags}

    for mid, m in lib["movies"].items():
        m["missing"] = mid not in found_ids
        key = m.get("dup_key")
        group = seen_by_dup_key.get(key, []) if key else []
        m["duplicate_of"] = [g for g in group if g !=
                             mid] if len(group) > 1 else []

    file_index, folder_index = build_category_index()
    for mid, m in lib["movies"].items():
        m_path = Path(m["path"])
        matched = set(file_index.get(m_path.stem.lower(), []))
        for p in m_path.parents:
            matched.update(folder_index.get(p.name.lower(), []))
        if matched:
            existing = set(m.get("tags", []))
            m["tags"] = list(existing | matched)

    save_library(lib)
    return lib


def generate_thumbnail(mid: str, video_path: str) -> bool:
    THUMBNAILS_DIR.mkdir(exist_ok=True)
    out_paths = [THUMBNAILS_DIR /
                 f"{mid}_{i+1}.jpg" for i in range(len(THUMBNAIL_TIMESTAMPS_PERCENT))]
    if all(p.exists() for p in out_paths):
        return True

    try:
        proc = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                              "default=noprint_wrappers=1:nokey=1", video_path], capture_output=True, text=True, timeout=15)
        duration = float(proc.stdout.strip())
    except:
        duration = None

    success = 0
    for i, percent in enumerate(THUMBNAIL_TIMESTAMPS_PERCENT):
        out = out_paths[i]
        if out.exists():
            success += 1
            continue
        ts = str(int(duration * (percent / 100))
                 ) if duration and duration > 10 else "5"
        try:
            subprocess.run([FFMPEG_PATH, "-y", "-ss", ts, "-i", video_path, "-frames:v", "1", "-vf",
                           "scale=300:300:force_original_aspect_ratio=decrease", "-q:v", "3", str(out)], capture_output=True, timeout=30)
            if out.exists():
                success += 1
        except:
            pass
    return success > 0


def generate_all_thumbnails():
    lib = load_library()
    res = {"generated": 0, "skipped": 0, "failed": 0, "deleted": 0}
    
    # Get all existing movie IDs
    existing_ids = set(lib["movies"].keys())
    
    # Clean up thumbnails for deleted movies
    if THUMBNAILS_DIR.exists():
        for thumb_file in THUMBNAILS_DIR.iterdir():
            if thumb_file.is_file() and thumb_file.suffix.lower() == '.jpg':
                # Extract mid from filename like "abc123_1.jpg"
                parts = thumb_file.stem.rsplit('_', 1)
                if len(parts) == 2:
                    mid = parts[0]
                    if mid not in existing_ids:
                        try:
                            thumb_file.unlink()
                            res["deleted"] += 1
                            print(f"Deleted thumbnail for removed movie ID: {mid}")
                        except Exception:
                            pass
    
    # Generate thumbnails for existing movies
    for mid, m in lib["movies"].items():
        if m.get("missing"):
            continue
        out_paths = [THUMBNAILS_DIR / f"{mid}_{i+1}.jpg" for i in range(len(THUMBNAIL_TIMESTAMPS_PERCENT))]
        if all(p.exists() for p in out_paths):
            res["skipped"] += 1
            continue
        if generate_thumbnail(mid, m["path"]):
            res["generated"] += 1
            print(f"Generated thumbnails for: {m.get('title', 'Unknown')}")
        else:
            res["failed"] += 1
            print(f"Failed to generate thumbnails for: {m.get('title', 'Unknown')}")
    return res


def detect_moved_files(lib):
    """Parcourt les groupes de doublons et retourne les paires suspectes de fichiers déplacés.

    Retourne une liste d'objets { old_mid, new_mid, title, old_path, new_path }.
    On considère un déplacement lorsque, pour un même dup_key, il y a exactement
    deux membres : un avec missing=True (ancien) et un avec missing=False (nouveau).
    Les paires stockées dans lib.get('dismissed_moves', []) sont ignorées.
    """
    by_dup = {}
    for mid, m in lib.get('movies', {}).items():
        k = m.get('dup_key')
        if not k:
            continue
        by_dup.setdefault(k, []).append((mid, m))

    dismissed = set(lib.get('dismissed_moves', []))
    res = []
    for k, items in by_dup.items():
        if len(items) != 2:
            continue
        (a_mid, a), (b_mid, b) = items[0], items[1]
        # exactly one missing True and exactly one missing False
        if bool(a.get('missing')) == bool(b.get('missing')):
            continue
        old_mid, old = (a_mid, a) if a.get('missing') else (b_mid, b)
        new_mid, new = (b_mid, b) if a.get('missing') else (a_mid, a)
        key = f"{old_mid}|{new_mid}"
        if key in dismissed:
            continue
        title = old.get('title') or new.get('title') or ''
        res.append({
            'old_mid': old_mid,
            'new_mid': new_mid,
            'title': title,
            'old_path': old.get('path'),
            'new_path': new.get('path')
        })
    return res


def open_file(path):
    if sys.platform.startswith("win"):
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


# ============================================================ #
#                      Serveur HTTP                            #
# ============================================================ #

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._serve_file(HTML_FILE, "text/html")
        elif parsed.path.startswith("/api/"):
            self._handle_api(parsed)
        else:
            self._serve_static(parsed.path)

    def _serve_file(self, path, mime):
        content = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.end_headers()
        self.wfile.write(content)

    def _serve_static(self, url_path):
        filename = url_path.lstrip("/")
        ext = Path(filename).suffix.lower()
        path = HTML_FILE.parent / filename
        if ".." not in url_path and path.exists() and ext in {".css", ".js", ".ico", ".png", ".jpg", ".svg", ".woff2", ".woff"}:
            self._serve_file(path, "text/css" if ext ==
                             ".css" else "application/javascript" if ext == ".js" else "image/jpeg")
        else:
            self._send_json({"error": "not found"}, 404)

    def _handle_api(self, parsed):
        lib = load_library()
        qs = parse_qs(parsed.query)
        if parsed.path == "/api/library":
            self._send_json(lib)
        elif parsed.path == "/api/moved":
            self._send_json(detect_moved_files(lib))
        elif parsed.path == "/api/scan":
            self._send_json(scan_movies())
        elif parsed.path == "/api/play":
            m = lib["movies"].get(qs.get("id", [None])[0])
            if m:
                open_file(m["path"])
                self._send_json({"ok": True})
            else:
                self._send_json({"error": "introuvable"}, 404)
        elif parsed.path == "/api/thumbnail":
            p = THUMBNAILS_DIR / f"{qs.get('id', [None])[0]}.jpg"
            if p.exists():
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.end_headers()
                self.wfile.write(p.read_bytes())
            else:
                self._send_json({"error": "not found"}, 404)
        elif parsed.path == "/api/thumbnails/generate":
            self._send_json(generate_all_thumbnails())
        elif parsed.path == "/api/reveal":
            m = lib["movies"].get(qs.get("id", [None])[0])
            if m:
                subprocess.Popen(["explorer", f"/select,{m['path']}"] if sys.platform.startswith(
                    "win") else ["xdg-open", str(Path(m['path']).parent)])
                self._send_json({"ok": True})
            else:
                self._send_json({"error": "introuvable"}, 404)

    def do_POST(self):
        body = json.loads(self.rfile.read(
            int(self.headers.get("Content-Length", 0))).decode("utf-8"))
        lib = load_library()
        path = urlparse(self.path).path

        if path == "/api/moved/confirm":
            old_mid = body.get('old_mid')
            new_mid = body.get('new_mid')
            if not old_mid or not new_mid or old_mid not in lib.get('movies', {}) or new_mid not in lib.get('movies', {}):
                self._send_json({"error": "invalid ids"}, 400)
                return
            old = lib['movies'][old_mid]
            new = lib['movies'][new_mid]

            # The old entry's metadata has priority.
            old['path'] = new.get('path')
            old['missing'] = False

            for pl_name, pl in lib.get('playlists', {}).items():
                new_pl = []
                seen = set()
                for mid in pl:
                    mid_to_add = old_mid if mid == new_mid else mid
                    if mid_to_add in seen:
                        continue
                    new_pl.append(mid_to_add)
                    seen.add(mid_to_add)
                lib['playlists'][pl_name] = new_pl

            # Replace references in duplicate_of lists across movies
            for m in lib.get('movies', {}).values():
                if 'duplicate_of' in m and isinstance(m['duplicate_of'], list):
                    m['duplicate_of'] = [old_mid if x == new_mid else x for x in m['duplicate_of']]

            # Remove new_mid
            lib['movies'].pop(new_mid, None)

            save_library(lib)
            self._send_json({"ok": True})
            return

        if path == "/api/moved/dismiss":
            old_mid = body.get('old_mid')
            new_mid = body.get('new_mid')
            if not old_mid or not new_mid:
                self._send_json({"error": "invalid ids"}, 400)
                return
            key = f"{old_mid}|{new_mid}"
            dismissed = lib.setdefault('dismissed_moves', [])
            if key not in dismissed:
                dismissed.append(key)
            save_library(lib)
            self._send_json({"ok": True})
            return

        if path == "/api/favorite":
            lib["movies"][body["id"]]["favorite"] = bool(body["value"])
        elif path == "/api/tags":
            lib["movies"][body["id"]]["tags"] = body["tags"]
        elif path == "/api/tag/rename":
            for m in lib["movies"].values():
                if body["old"] in m.get("tags", []):
                    m["tags"] = [body["new"] if t ==
                                 body["old"] else t for t in m["tags"]]
        elif path == "/api/tag/delete":
            for m in lib["movies"].values():
                if body["tag"] in m.get("tags", []):
                    m["tags"].remove(body["tag"])
        elif path == "/api/playlist/create":
            lib["playlists"][body["name"]] = []
        elif path == "/api/playlist/delete":
            lib["playlists"].pop(body["name"], None)
        elif path == "/api/playlist/toggle":
            pl = lib["playlists"][body["name"]]
            if body["id"] in pl:
                pl.remove(body["id"])
            else:
                pl.append(body["id"])

        save_library(lib)
        self._send_json({"ok": True, "playlists": lib.get("playlists")})


def main():
    if not DATA_FILE.exists():
        scan_movies()
    server = ThreadingHTTPServer(("localhost", PORT), Handler)
    print(f"Cinémathèque : http://localhost:{PORT}")
    webbrowser.open(f"http://localhost:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
