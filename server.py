#!/usr/bin/env python3
"""
Cinémathèque — organiseur de films local
==========================================
Aucune dépendance externe. Fonctionne avec Python 3.8+.

UTILISATION
-----------
1. Ouvre config.py (à côté de ce script) et modifie MOVIE_ROOTS avec les
   chemins de tes dossiers de films (peu importe le désordre à l'intérieur).
   config.py ne sera jamais écrasé si tu me redemandes des modifications
   sur server.py ou index.html.
2. Lance :  python server.py
3. Ton navigateur s'ouvre automatiquement sur http://localhost:8420

Le script scanne récursivement chaque dossier de MOVIE_ROOTS, à n'importe
quelle profondeur, sans tenir compte de l'organisation en sous-dossiers :
tous les films remontent dans une seule liste plate, aucune étiquette
n'est créée à partir de l'emplacement du fichier.

Le script détecte les doublons potentiels : deux fichiers dont le titre
normalisé (sans les mentions 1080p/FRENCH/BluRay/etc.) se ressemble sont
signalés pour que tu puisses vérifier et faire le ménage.

Favoris, catégories perso et playlists sont gérés depuis l'interface et
stockés dans library.json (à côté de ce script), indépendamment de tes
dossiers réels — plus besoin de raccourcis/liens.
"""

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
        MOVIE_ROOTS,
        IGNORED_FOLDER_NAMES,
        VIDEO_EXTENSIONS,
        PORT,
        NOISE_WORDS as _NOISE_WORDS,
        AUTO_TAG_FROM_FOLDERS,
        IGNORED_TAG_NAMES,
        CATEGORIES_ROOTS,
        THUMBNAILS_ENABLED,
        FFMPEG_PATH,
        THUMBNAIL_TIMESTAMPS_PERCENT,
    )
except ImportError:
    print("[!] config.py introuvable à côté de server.py.")
    print("    Crée-le avec au minimum une variable MOVIE_ROOTS = [...]")
    sys.exit(1)

DATA_FILE = Path(__file__).parent / "library.json"
HTML_FILE = Path(__file__).parent / "index.html"
THUMBNAILS_DIR = Path(__file__).parent / "thumbnails"

# ============================================================
# Stockage
# ============================================================


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
    """Réduit un titre de fichier à une forme comparable, pour repérer les
    doublons malgré des noms de fichiers différents (qualité, langue...)."""
    t = title.lower()
    # retire (2019), [FR], {x264}...
    t = re.sub(r"[\[\(\{].*?[\]\)\}]", " ", t)
    t = re.sub(r"[._\-]", " ", t)
    for word in _NOISE_WORDS:
        t = re.sub(rf"\b{re.escape(word)}\b", " ", t)
    # l'année est traitée séparément, voir extract_year
    t = _YEAR_RE.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def extract_year(title: str):
    """Renvoie la première année à 4 chiffres (1900-2099) trouvée dans le
    titre du fichier, ou None si absente."""
    match = _YEAR_RE.search(title)
    return match.group(0) if match else None


def duplicate_key(norm_title: str, year):
    """Clé de regroupement pour la détection de doublons.
    - Titres trop courts/génériques (< 3 caractères) ignorés : trop de
      faux positifs (ex: "vs", "ok").
    - Si une année est présente, elle fait partie de la clé : deux films
      de même titre mais d'années différentes (remakes, suites au même
      nom) ne sont PLUS considérés comme doublons.
    - Si l'année est absente, on compare par titre seul (moins strict,
      pour les fichiers mal nommés qui n'ont pas d'année du tout)."""
    if len(norm_title) < 3:
        return None
    return f"{norm_title}|{year}" if year else norm_title


def extract_tags_from_path(file_path: str, root_path: Path) -> list:
    """Extrait les étiquettes basées sur les dossiers parents[cite: 1]."""
    if not AUTO_TAG_FROM_FOLDERS:
        return []
    try:
        rel_path = Path(file_path).relative_to(root_path)
        parts = rel_path.parts[:-1]  # Exclut le nom du fichier lui-même
        tags = [re.sub('_+', ' ', p).strip() for p in parts if p and p.lower()
                and p.replace('_', '') not in IGNORED_TAG_NAMES]
        return list(tags)
    except ValueError:
        return []


def _lnk_stem(item) -> str:
    """Retire le suffixe Windows 'Raccourci'/'Shortcut' du nom d'un .lnk
    pour retrouver le nom d'origine du fichier ou dossier cible."""
    LNK_SUFFIXES = [" - raccourci", " - shortcut", " - lien symbolique"]
    stem = item.stem
    stem_lower = stem.lower()
    for suffix in LNK_SUFFIXES:
        if stem_lower.endswith(suffix):
            stem = stem[:len(stem) - len(suffix)]
            break
    return stem.strip()


def build_category_index():
    """Parcourt CATEGORIES_ROOTS et construit deux index basés sur le NOM
    des raccourcis .lnk (sans résoudre leur cible via PowerShell).

    Windows nomme les raccourcis "<nom> - Raccourci.lnk". On retire ce
    suffixe pour retrouver le nom d'origine, puis on compare avec les noms
    de fichiers et dossiers lors du scan des films.

    Retourne :
      file_index   : { nom_normalisé : [tag, ...] }
      folder_index : { nom_normalisé : [tag, ...] }
    """
    file_index = defaultdict(list)
    folder_index = defaultdict(list)

    roots = CATEGORIES_ROOTS if isinstance(CATEGORIES_ROOTS, list) else (
        [CATEGORIES_ROOTS] if CATEGORIES_ROOTS else [])

    for categories_root in roots:
        cat_root = Path(categories_root)
        if not cat_root.exists():
            print(
                f"[!] CATEGORIES_ROOTS introuvable, ignoré : {categories_root}")
            continue

        for cat_dir in cat_root.iterdir():
            if not cat_dir.is_dir():
                continue
            tag_name = re.sub(r'_+', ' ', cat_dir.name).strip()

            for item in cat_dir.iterdir():
                if item.suffix.lower() != ".lnk":
                    continue
                stem = _lnk_stem(item)
                if not stem:
                    continue
                key = stem.lower()
                file_index[key].append(tag_name)
                folder_index[key].append(tag_name)

    total = sum(len(v) for v in file_index.values())
    print(
        f"[cat] Index construit : {total} entrée(s) sur {len(file_index)} nom(s) unique(s)")
    return file_index, folder_index


def scan_movies():
    # Parcourt MOVIE_ROOTS à n'importe quelle profondeur, fusionne avec les
    # données existantes (favoris/catégories/playlists conservés si le
    # fichier existe déjà), et détecte les doublons potentiels."""
    lib = load_library()
    found_ids = set()
    seen_by_dup_key = defaultdict(list)  # pour la détection de doublons

    for root in MOVIE_ROOTS:
        root_path = Path(root)
        if not root_path.exists():
            print(f"[!] Dossier introuvable, ignoré : {root}")
            continue

        for dirpath, dirnames, filenames in os.walk(root_path):
            # On ignore les dossiers "Favoris"/"Catégories" (raccourcis)
            # pour ne pas scanner deux fois les mêmes fichiers.
            dirnames[:] = [d for d in dirnames if d.lower()
                           not in IGNORED_FOLDER_NAMES]

            for filename in filenames:
                ext = Path(filename).suffix.lower()
                if ext not in VIDEO_EXTENSIONS:
                    continue

                full_path = str(Path(dirpath) / filename)
                mid = movie_id(full_path)
                found_ids.add(mid)

                try:
                    size_bytes = os.path.getsize(full_path)
                except OSError:
                    size_bytes = None

                title = Path(filename).stem
                norm = normalize_title(title)
                year = extract_year(title)
                dup_key = duplicate_key(norm, year)
                if dup_key:
                    seen_by_dup_key[dup_key].append(mid)

                # Extraction des étiquettes des dossiers parents[cite: 1]
                path_tags = extract_tags_from_path(full_path, root_path)

                if mid in lib["movies"]:
                    lib["movies"][mid]["path"] = full_path
                    lib["movies"][mid]["title"] = title
                    lib["movies"][mid]["norm_title"] = norm
                    lib["movies"][mid]["year"] = year
                    lib["movies"][mid]["dup_key"] = dup_key
                    lib["movies"][mid]["size_bytes"] = size_bytes
                    # Fusionne intelligemment les tags automatiques avec les existants
                    existing_tags = lib["movies"][mid].get("tags", [])
                    for pt in path_tags:
                        if pt not in existing_tags:
                            existing_tags.append(pt)
                    lib["movies"][mid]["tags"] = existing_tags
                else:
                    lib["movies"][mid] = {
                        "path": full_path,
                        "title": title,
                        "norm_title": norm,
                        "year": year,
                        "dup_key": dup_key,
                        "size_bytes": size_bytes,
                        "favorite": False,
                        "categories": [],
                        # Étiquettes initiales basées sur les dossiers[cite: 1]
                        "tags": path_tags,
                    }

    # On ne supprime pas les films disparus automatiquement (disque externe
    # débranché, etc.) — on les marque juste comme "absent" pour info.
    for mid, movie in lib["movies"].items():
        movie["missing"] = mid not in found_ids

    # Doublons : même titre normalisé ET même année (si connue) retrouvés
    # dans plusieurs fichiers.
    for mid, movie in lib["movies"].items():
        key = movie.get("dup_key")
        group = seen_by_dup_key.get(key, []) if key else []
        others = [g for g in group if g != mid]
        movie["duplicate_of"] = others if len(group) > 1 else []

    # Tags issus du dossier Catégories — correspondance par nom de fichier/dossier
    file_index, folder_index = build_category_index()
    if file_index:
        for mid, movie in lib["movies"].items():
            movie_path = Path(movie["path"])
            matched_tags = []

            # Correspondance par nom de fichier vidéo (stem normalisé)
            file_key = movie_path.stem.lower()
            if file_key in file_index:
                matched_tags.extend(file_index[file_key])

            # Correspondance par nom de dossier parent (tous les niveaux)
            for parent in movie_path.parents:
                folder_key = parent.name.lower()
                if folder_key and folder_key in folder_index:
                    matched_tags.extend(folder_index[folder_key])

            if matched_tags:
                existing = movie.get("tags", [])
                existing_lower = {t.lower() for t in existing}
                added = 0
                for tag in matched_tags:
                    if tag.lower() not in existing_lower:
                        existing.append(tag)
                        existing_lower.add(tag.lower())
                        added += 1
                movie["tags"] = existing
                if added:
                    print(
                        f"  [cat] {movie_path.name} <- {list(set(matched_tags))}")

    save_library(lib)
    return lib


def check_ffmpeg_available() -> bool:
    """Vérifie que ffmpeg est accessible avant de lancer une génération."""
    try:
        subprocess.run([FFMPEG_PATH, "-version"],
                       capture_output=True, timeout=5)
        return True
    except FileNotFoundError:
        return False
    except Exception:
        return True  # présent mais erreur secondaire, on tente quand même


def get_video_duration(path: str):
    """Durée de la vidéo en secondes via ffprobe (fourni avec ffmpeg)."""
    try:
        ffprobe_path = FFMPEG_PATH.replace(
            "ffmpeg", "ffprobe") if "ffmpeg" in FFMPEG_PATH.lower() else "ffprobe"
        result = subprocess.run(
            [ffprobe_path, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=15
        )
        return float(result.stdout.strip())
    except Exception:
        return None


def generate_thumbnail(mid: str, video_path: str) -> bool:
    """Extrait 3 images à différents pourcentages de la durée de la vidéo
    (THUMBNAIL_TIMESTAMPS_PERCENT), largeur max 300px, sauvegardées en
    thumbnails/<id>_1.jpg, <id>_2.jpg, <id>_3.jpg."""
    THUMBNAILS_DIR.mkdir(exist_ok=True)
    out_paths = [THUMBNAILS_DIR /
                 f"{mid}_{i+1}.jpg" for i in range(len(THUMBNAIL_TIMESTAMPS_PERCENT))]

    if all(p.exists() for p in out_paths):
        return True  # les 3 sont déjà générées

    duration = get_video_duration(video_path)
    success_count = 0

    for i, percent in enumerate(THUMBNAIL_TIMESTAMPS_PERCENT):
        out_path = out_paths[i]
        if out_path.exists():
            success_count += 1
            continue

        timestamp = "5"
        if duration and duration > 10:
            timestamp = str(int(duration * (percent / 100)))

        try:
            subprocess.run(
                [
                    FFMPEG_PATH, "-y", "-ss", timestamp, "-i", video_path,
                    "-frames:v", "1",
                    "-vf", "scale=300:300:force_original_aspect_ratio=decrease",
                    "-q:v", "3", str(out_path)
                ],
                capture_output=True, timeout=30
            )
            if out_path.exists() and out_path.stat().st_size > 0:
                success_count += 1
        except Exception as e:
            print(f"[thumb] Échec ({i+1}/3) pour {video_path} : {e}")

    return success_count > 0  # au moins une miniature générée


def generate_all_thumbnails():
    """Génère les miniatures manquantes pour tous les films non introuvables.
    Ne régénère jamais une miniature déjà présente (rapide sur les scans suivants)."""
    if not check_ffmpeg_available():
        return {"error": f"ffmpeg introuvable (chemin configuré : {FFMPEG_PATH}). Installe ffmpeg ou corrige FFMPEG_PATH dans config.py."}

    lib = load_library()
    generated, skipped, failed = 0, 0, 0
    THUMBNAILS_DIR.mkdir(exist_ok=True)

    for mid, movie in lib["movies"].items():
        if movie.get("missing"):
            continue
        out_path = THUMBNAILS_DIR / f"{mid}.jpg"
        if out_path.exists():
            skipped += 1
            continue
        print(f"[thumb] Génération : {movie['title']}")
        if generate_thumbnail(mid, movie["path"]):
            generated += 1
        else:
            failed += 1

    print(
        f"[thumb] Terminé — générées: {generated}, déjà présentes: {skipped}, échecs: {failed}")
    return {"generated": generated, "skipped": skipped, "failed": failed}


def open_file_with_default_player(path: str):
    if sys.platform.startswith("win"):
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def reveal_in_file_manager(path: str):
    """Ouvre l'explorateur de fichiers avec le fichier sélectionné/visible,
    pour comparer et supprimer soi-même en cas de doublon."""
    if sys.platform.startswith("win"):
        subprocess.Popen(["explorer", f"/select,{path}"])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path])
    else:
        subprocess.Popen(["xdg-open", str(Path(path).parent)])


# ============================================================
# Serveur HTTP
# ============================================================
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # silence les logs par défaut

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    # ---------------- GET ----------------
    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/":
            self._serve_html()
        elif parsed.path.startswith("/api/"):
            self._handle_api_get(parsed)
        else:
            self._serve_static(parsed.path)

    def _serve_static(self, url_path):
        """Sert les fichiers statiques (.css, .js, etc.) depuis le même
        dossier que index.html. Seule une liste blanche d'extensions est
        autorisée pour éviter d'exposer library.json ou config.py."""
        ALLOWED_EXTENSIONS = {
            ".css":  "text/css; charset=utf-8",
            ".js":   "application/javascript; charset=utf-8",
            ".ico":  "image/x-icon",
            ".png":  "image/png",
            ".jpg":  "image/jpeg",
            ".svg":  "image/svg+xml",
            ".woff2": "font/woff2",
            ".woff":  "font/woff",
        }
        # Sécurité : interdit les chemins avec ".." pour éviter les traversées
        if ".." in url_path:
            self._send_json({"error": "forbidden"}, 403)
            return

        filename = url_path.lstrip("/")
        ext = Path(filename).suffix.lower()

        if ext not in ALLOWED_EXTENSIONS:
            self._send_json({"error": "not found"}, 404)
            return

        file_path = HTML_FILE.parent / filename
        if not file_path.exists():
            self._send_json({"error": f"{filename} introuvable"}, 404)
            return

        content = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ALLOWED_EXTENSIONS[ext])
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _handle_api_get(self, parsed):
        """Gère tous les endpoints GET /api/..."""
        if parsed.path == "/api/library":
            self._send_json(load_library())
        elif parsed.path == "/api/scan":
            self._send_json(scan_movies())
        elif parsed.path == "/api/play":
            qs = parse_qs(parsed.query)
            mid = qs.get("id", [None])[0]
            lib = load_library()
            movie = lib["movies"].get(mid)
            if not movie:
                self._send_json({"error": "introuvable"}, 404)
                return
            try:
                open_file_with_default_player(movie["path"])
                self._send_json({"ok": True})
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        elif parsed.path == "/api/thumbnail":
            qs = parse_qs(parsed.query)
            mid = qs.get("id", [None])[0]
            thumb_path = THUMBNAILS_DIR / f"{mid}.jpg"
            if not thumb_path.exists():
                self._send_json({"error": "not found"}, 404)
                return
            content = thumb_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "public, max-age=86400")
            self.end_headers()
            self.wfile.write(content)

        elif parsed.path == "/api/thumbnails/generate":
            self._send_json(generate_all_thumbnails())

        elif parsed.path == "/api/reveal":
            qs = parse_qs(parsed.query)
            mid = qs.get("id", [None])[0]
            lib = load_library()
            movie = lib["movies"].get(mid)
            if not movie:
                self._send_json({"error": "introuvable"}, 404)
                return
            try:
                reveal_in_file_manager(movie["path"])
                self._send_json({"ok": True})
            except Exception as e:
                self._send_json({"error": str(e)}, 500)
        else:
            self._send_json({"error": "not found"}, 404)

    # ---------------- POST ----------------
    def do_POST(self):
        parsed = urlparse(self.path)
        body = self._read_json_body()
        lib = load_library()

        if parsed.path == "/api/favorite":
            mid = body.get("id")
            if mid in lib["movies"]:
                lib["movies"][mid]["favorite"] = bool(body.get("value"))
                save_library(lib)
                self._send_json({"ok": True})
            else:
                self._send_json({"error": "introuvable"}, 404)

        elif parsed.path == "/api/categories":
            mid = body.get("id")
            categories = body.get("categories", [])
            if mid in lib["movies"]:
                lib["movies"][mid]["categories"] = categories
                save_library(lib)
                self._send_json({"ok": True})
            else:
                self._send_json({"error": "introuvable"}, 404)

        elif parsed.path == "/api/tags":
            mid = body.get("id")
            tags = body.get("tags", [])
            if mid in lib["movies"]:
                lib["movies"][mid]["tags"] = tags
                save_library(lib)
                self._send_json({"ok": True})
            else:
                self._send_json({"error": "introuvable"}, 404)

        elif parsed.path == "/api/tag/rename":
            old_name = body.get("old")
            new_name = body.get("new", "").strip()
            if old_name and new_name:
                for m in lib["movies"].values():
                    if "tags" in m and old_name in m["tags"]:
                        m["tags"] = [new_name if t ==
                                     old_name else t for t in m["tags"]]
                save_library(lib)
                self._send_json({"ok": True})
            else:
                self._send_json({"error": "Nom invalide"}, 400)

        elif parsed.path == "/api/tag/delete":
            tag_name = body.get("tag")
            if tag_name:
                for m in lib["movies"].values():
                    if "tags" in m and tag_name in m["tags"]:
                        m["tags"] = [t for t in m["tags"] if t != tag_name]
                save_library(lib)
                self._send_json({"ok": True})
            else:
                self._send_json({"error": "Étiquette invalide"}, 400)

        elif parsed.path == "/api/playlist/create":
            name = body.get("name", "").strip()
            if name and name not in lib["playlists"]:
                lib["playlists"][name] = []
                save_library(lib)
            self._send_json({"ok": True, "playlists": lib["playlists"]})

        elif parsed.path == "/api/playlist/delete":
            name = body.get("name", "")
            lib["playlists"].pop(name, None)
            save_library(lib)
            self._send_json({"ok": True, "playlists": lib["playlists"]})

        elif parsed.path == "/api/playlist/rename":
            old_name = body.get("old_name", "")
            new_name = body.get("new_name", "").strip()

            if not new_name:
                self._send_json({"error": "nom invalide"}, 400)
                return
            if old_name not in lib["playlists"]:
                self._send_json({"error": "playlist introuvable"}, 404)
                return
            if new_name != old_name and new_name in lib["playlists"]:
                self._send_json({"error": "une playlist porte déjà ce nom"}, 409)
                return

            # Préserve l'ordre d'insertion en reconstruisant le dict
            lib["playlists"] = {
                (new_name if k == old_name else k): v
                for k, v in lib["playlists"].items()
            }
            save_library(lib)
            self._send_json({"ok": True, "playlists": lib["playlists"]})

        elif parsed.path == "/api/playlist/toggle":
            name = body.get("name")
            mid = body.get("id")
            if name in lib["playlists"]:
                if mid in lib["playlists"][name]:
                    lib["playlists"][name].remove(mid)
                else:
                    lib["playlists"][name].append(mid)
                save_library(lib)
                self._send_json({"ok": True, "playlists": lib["playlists"]})
            else:
                self._send_json({"error": "playlist introuvable"}, 404)

        else:
            self._send_json({"error": "not found"}, 404)

    def _serve_html(self):
        if not HTML_FILE.exists():
            self._send_json({"error": "index.html manquant"}, 500)
            return
        content = HTML_FILE.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def main():
    if not DATA_FILE.exists():
        scan_movies()

    server = ThreadingHTTPServer(("localhost", PORT), Handler)
    url = f"http://localhost:{PORT}"
    print(f"Cinémathèque lancée sur {url}")
    print("Ctrl+C pour arrêter.")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt du serveur.")
        server.shutdown()


if __name__ == "__main__":
    main()