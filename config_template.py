# ============================================================
# Configuration de la Cinémathèque
# ============================================================
# Ce fichier n'est jamais écrasé quand server.py ou index.html sont mis à
# jour : tu peux modifier tes chemins ici en toute tranquillité.

MOVIE_ROOTS = [
    # Remplace par tes vrais chemins de dossiers de films.
    # Peu importe la profondeur ou le nombre de niveaux de sous-dossiers,
    # peu importe s'il y a des films en vrac directement dedans.
    # Tu peux en mettre plusieurs, un par ligne :
    r"C:\Films",
    r"E:\Films",
]

# Dossiers à ignorer pendant le scan (noms exacts, insensible à la casse).
# Utile pour exclure d'anciens dossiers de raccourcis "Favoris"/"Catégories"
# si tu les gardes encore à côté de tes vrais dossiers de films.
IGNORED_FOLDER_NAMES = {}

# Active ou désactive la génération automatique d'étiquettes via les dossiers parents
AUTO_TAG_FROM_FOLDERS = True
IGNORED_TAG_NAMES = {"a trier", "autres", "others"}

# Extensions de fichiers considérées comme des films.
VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".m4v", ".flv"}

# Chemin(s) vers ton dossier de catégories avec raccourcis.
CATEGORIES_ROOTS = [
    r"C:\Films\_Categories",
]

# Miniatures — extraites localement depuis chaque vidéo via ffmpeg
THUMBNAILS_ENABLED = True
# ou chemin complet si ffmpeg n'est pas dans le PATH, ex: r"C:\ffmpeg\bin\ffmpeg.exe"
FFMPEG_PATH = "ffmpeg"
# position dans la vidéo (en % de la durée) où prendre l'image
# THUMBNAIL_TIMESTAMP_PERCENT = 15 
THUMBNAIL_TIMESTAMPS_PERCENT = [15, 50, 85]

# Port du serveur local (change-le seulement en cas de conflit avec un
# autre programme sur ton PC).
PORT = 8420

# Mots retirés du titre pour comparer deux fichiers et détecter les
# doublons (qualité, langue, groupe de release, etc.). Ajoute les tiens
# si tes fichiers utilisent d'autres conventions de nommage.
NOISE_WORDS = [
    "1080p", "720p", "2160p", "4k", "bluray", "blu-ray", "webrip", "web-dl",
    "webdl", "hdtv", "dvdrip", "brrip", "bdrip", "x264", "x265", "hevc",
    "aac", "ac3", "dts", "french", "vostfr", "vff", "multi", "truefrench",
    "xvid", "h264", "h265", "remux", "hdlight", "extended", "director's cut",
]
