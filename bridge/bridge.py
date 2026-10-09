"""
PLATINE Bridge v12 - SMTC + Spotify (Premium + Free)
WebSocket SMTC : ws://127.0.0.1:8974
API HTTP Spotify : http://127.0.0.1:8976
"""
import asyncio
import base64
import ctypes
import json
import logging
import os
import random
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from ctypes import wintypes
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("platine-bridge")

try:
    from winsdk.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as GSMTC,
    )
    from winsdk.windows.storage.streams import DataReader
    import websockets
except ImportError as e:
    log.critical(f"Module manquant : {e}\npip install winsdk websockets")
    raise SystemExit(1)

try:
    import spotipy
    from spotipy.oauth2 import SpotifyOAuth
except ImportError:
    spotipy = None
    log.warning("spotipy non installe : mode Spotify desactive")

PORT_WS = 8974
PORT_HTTP = 8976
REDIRECT_URI = f"http://127.0.0.1:{PORT_HTTP}/callback"
SCOPE = ("user-read-playback-state user-modify-playback-state "
         "user-library-read playlist-read-private playlist-read-collaborative")

clients = set()
last_state = {}
spotify = None
MAIN_LOOP = None

# ═══════════════════════════════════════════════════════
#  WIN32 : garder Spotify en arriere-plan
# ═══════════════════════════════════════════════════════
_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32
_SW_MINIMIZE = 6
_ENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)


def _get_foreground():
    return _user32.GetForegroundWindow()


def _hwnd_process_name(hwnd):
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h = _kernel32.OpenProcess(0x1000, False, pid.value)
    if not h:
        return ""
    buf = ctypes.create_unicode_buffer(512)
    size = wintypes.DWORD(512)
    ok = _kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size))
    _kernel32.CloseHandle(h)
    return buf.value if ok else ""


def _find_spotify_hwnds():
    found = []

    def cb(hwnd, lparam):
        if _user32.IsWindowVisible(hwnd):
            name = _hwnd_process_name(hwnd)
            if name.lower().endswith("spotify.exe"):
                found.append(hwnd)
        return True

    proc = _ENUMPROC(cb)
    _user32.EnumWindows(proc, 0)
    return found


# ═══════════════════════════════════════════════════════
#  CONTROLE SMTC DEPUIS UN THREAD (pause / reprise)
# ═══════════════════════════════════════════════════════

def pause_current_sync():
    """Met en pause la lecture en cours (appele depuis le thread HTTP)."""
    async def _pause():
        mgr = await GSMTC.request_async()
        session = await get_active_session(mgr)
        if session:
            status = session.get_playback_info().playback_status
            if status == 4:
                await session.try_pause_async()
                log.info("Lecture en cours mise en pause")
    try:
        fut = asyncio.run_coroutine_threadsafe(_pause(), MAIN_LOOP)
        fut.result(timeout=3)
    except Exception as e:
        log.debug(f"Pause SMTC echouee : {e}")


def ensure_playing_sync():
    """Relance la lecture si Spotify n'a pas demarre tout seul."""
    async def _play():
        mgr = await GSMTC.request_async()
        session = await get_active_session(mgr)
        if session:
            status = session.get_playback_info().playback_status
            if status != 4:
                await session.try_play_async()
                log.info("Reprise de lecture forcee")
    try:
        fut = asyncio.run_coroutine_threadsafe(_play(), MAIN_LOOP)
        fut.result(timeout=3)
    except Exception as e:
        log.debug(f"Reprise lecture echouee : {e}")


def _post_launch_thread(prev_fg):
    """Apres lancement : verifie la lecture, minimise Spotify, rend le focus."""
    time.sleep(1.5)
    ensure_playing_sync()
    for delay in (0.5, 2.0, 5.0):
        time.sleep(delay)
        hwnds = _find_spotify_hwnds()
        if hwnds:
            for h in hwnds:
                _user32.ShowWindow(h, _SW_MINIMIZE)
            if prev_fg and _user32.IsWindow(prev_fg):
                _user32.keybd_event(0x12, 0, 0, 0)
                _user32.keybd_event(0x12, 0, 2, 0)
                _user32.SetForegroundWindow(prev_fg)
            return


# ═══════════════════════════════════════════════════════
#  CHEMINS / CONFIG
# ═══════════════════════════════════════════════════════

def _dirs():
    d = []
    if getattr(sys, "frozen", False):
        d.append(os.path.dirname(sys.executable))
    d.append(os.path.dirname(os.path.abspath(__file__)))
    d.append(os.path.join(os.path.expanduser("~"), "PLATINE"))
    d.append(r"C:\platine\bridge")
    return d


def _find(name):
    for dd in _dirs():
        p = os.path.join(dd, name)
        if os.path.exists(p):
            return p
    return os.path.join(_dirs()[0], name)


CACHE_PATH = _find(".spotify_cache")


def load_spotify_credentials():
    creds_path = _find("credentials.txt")
    client_id = os.environ.get("SPOTIFY_CLIENT_ID", "")
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET", "")
    sp_dc = os.environ.get("SPOTIFY_SP_DC", "")
    if os.path.exists(creds_path):
        with open(creds_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("CLIENT_ID="):
                    client_id = line.split("=", 1)[1].strip()
                elif line.startswith("CLIENT_SECRET="):
                    client_secret = line.split("=", 1)[1].strip()
                elif line.startswith("SP_DC="):
                    sp_dc = line.split("=", 1)[1].strip()
    return client_id, client_secret, sp_dc


def _make_auth():
    client_id, client_secret, _ = load_spotify_credentials()
    return SpotifyOAuth(
        client_id=client_id, client_secret=client_secret,
        redirect_uri=REDIRECT_URI, scope=SCOPE,
        cache_path=CACHE_PATH, open_browser=False,
    )


def init_spotify():
    global spotify
    if spotipy is None:
        return False
    client_id, client_secret, _ = load_spotify_credentials()
    if not client_id or not client_secret:
        log.warning("Spotify non configure : creer credentials.txt")
        return False
    try:
        auth = _make_auth()
        if auth.get_cached_token() is None:
            log.info("Ouverture du navigateur pour authentification Spotify...")
            webbrowser.open(auth.get_authorize_url())
            return "pending"
        spotify = spotipy.Spotify(auth_manager=auth)
        log.info("Spotify connecte (OAuth) !")
        return True
    except Exception as e:
        log.error(f"Init Spotify echouee : {e}")
        return False


def exchange_code_for_token(code):
    global spotify
    auth = _make_auth()
    auth.get_access_token(code, as_dict=True)
    spotify = spotipy.Spotify(auth_manager=auth)
    log.info("Spotify authentifie avec succes !")


# ═══════════════════════════════════════════════════════
#  STRATEGIES DE RECUPERATION DES TITRES
# ═══════════════════════════════════════════════════════

_cc_cache = {"token": None, "exp": 0}


def get_client_credentials_token():
    if _cc_cache["token"] and time.time() < _cc_cache["exp"] - 60:
        return _cc_cache["token"]
    cid, csec, _ = load_spotify_credentials()
    if not cid or not csec:
        return None
    data = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
    req = urllib.request.Request(
        "https://accounts.spotify.com/api/token",
        data=data,
        headers={"Authorization": "Basic " +
                 base64.b64encode(f"{cid}:{csec}".encode()).decode()},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            j = json.loads(resp.read().decode())
        _cc_cache["token"] = j["access_token"]
        _cc_cache["exp"] = time.time() + int(j.get("expires_in", 3600))
        return _cc_cache["token"]
    except Exception as e:
        log.debug(f"Client credentials echoue : {e}")
        return None


_web_token_cache = {"token": None, "exp": 0}


def get_web_player_token():
    if _web_token_cache["token"] and time.time() < _web_token_cache["exp"] - 60:
        return _web_token_cache["token"]
    _, _, sp_dc = load_spotify_credentials()
    if not sp_dc:
        return None
    req = urllib.request.Request(
        "https://open.spotify.com/get_access_token?reason=transport&productType=web_player",
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Cookie": f"sp_dc={sp_dc}",
            "Accept": "application/json",
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        token = data.get("accessToken")
        exp_ms = data.get("accessTokenExpirationTimestampMs", 0)
        _web_token_cache["token"] = token
        _web_token_cache["exp"] = exp_ms / 1000.0
        log.info("Token Web Player obtenu avec succes")
        return token
    except Exception as e:
        log.debug(f"Web Player token echoue : {e}")
        return None


def fetch_tracks_api(playlist_id, token):
    url = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks?limit=100&fields=items.track.uri,next"
    tracks = []
    while url:
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "PLATINE/1.0",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            j = json.loads(resp.read().decode())
        for item in j.get("items", []):
            tr = item.get("track") or {}
            if tr.get("uri"):
                tracks.append(tr["uri"])
        url = j.get("next")
    return tracks


def scrape_playlist_tracks(playlist_id):
    """Utilise l'URL embed publique Spotify (toujours accessible)."""
    url = f"https://open.spotify.com/embed/playlist/{playlist_id}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", "ignore")
        log.info(f"Embed : {len(html)} octets recus")
    except Exception as e:
        log.warning(f"Embed illisible ({e})")
        return []

    tracks = []
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
    if m:
        tracks = re.findall(r'spotify:track:[A-Za-z0-9]{10,}', m.group(1))
        log.info(f"Embed __NEXT_DATA__ : {len(tracks)} URIs")

    if not tracks:
        tracks = re.findall(r'spotify:track:[A-Za-z0-9]{10,}', html)
        log.info(f"Embed html brut : {len(tracks)} URIs")

    return list(dict.fromkeys(tracks))


def fetch_all_tracks(playlist_id):
    tok = get_web_player_token()
    if tok:
        try:
            tracks = fetch_tracks_api(playlist_id, tok)
            if tracks:
                log.info(f"Web Player : {len(tracks)} titres")
                return tracks
        except Exception as e:
            log.debug(f"Web Player echoue : {e}")

    if spotify is not None:
        try:
            tracks = []
            results = spotify.playlist_tracks(playlist_id, fields="items.track.uri")
            while results:
                for item in results.get("items", []):
                    if item.get("track") and item["track"].get("uri"):
                        tracks.append(item["track"]["uri"])
                results = spotify.next(results) if results.get("next") else None
            if tracks:
                log.info(f"OAuth : {len(tracks)} titres")
                return tracks
        except Exception as e:
            log.debug(f"OAuth echoue : {e}")

    tok = get_client_credentials_token()
    if tok:
        try:
            tracks = fetch_tracks_api(playlist_id, tok)
            if tracks:
                log.info(f"Client credentials : {len(tracks)} titres")
                return tracks
        except Exception as e:
            log.debug(f"Client credentials echoue : {e}")

    return scrape_playlist_tracks(playlist_id)


# ═══════════════════════════════════════════════════════
#  API HTTP
# ═══════════════════════════════════════════════════════

class SpotifyHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self._cors()
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/callback":
            qs = parse_qs(parsed.query)
            code = qs.get("code", [None])[0]
            if code:
                try:
                    exchange_code_for_token(code)
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(
                        b"<h2>PLATINE connecte a Spotify !</h2>"
                        b"<p>Tu peux fermer cet onglet.</p>")
                except Exception as e:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(str(e).encode())
            else:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Code manquant")
            return

        if parsed.path == "/status":
            self._json(200, {"spotify": spotify is not None})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length else ""

        if parsed.path in ("/play", "/play_local"):
            try:
                data = json.loads(body) if body else {}
                playlist_id = data.get("playlist_id")
                if not playlist_id:
                    self._json(400, {"error": "playlist_id requis"})
                    return
                tracks = fetch_all_tracks(playlist_id)
                if not tracks:
                    self._json(404, {"error": "Playlist vide ou inaccessible"})
                    return
                chosen = random.choice(tracks)

                # 1) Tentative lecture en contexte playlist (Premium)
                played_in_context = False
                if spotify is not None:
                    try:
                        spotify.start_playback(
                            context_uri=f"spotify:playlist:{playlist_id}",
                            offset={"uri": chosen},
                        )
                        played_in_context = True
                        log.info(f"Lecture en contexte playlist : {chosen}")
                    except Exception as e:
                        log.debug(f"start_playback refuse ({e}) -> repli URI")

                # 2) Repli Free : pause actuelle, puis ouverture URI
                if not played_in_context:
                    pause_current_sync()
                    time.sleep(0.3)
                    prev_fg = _get_foreground()
                    prev_is_spotify = "spotify.exe" in _hwnd_process_name(prev_fg).lower()
                    log.info(f"Lecture de : {chosen}")
                    os.startfile(chosen)
                    if not prev_is_spotify:
                        threading.Thread(
                            target=_post_launch_thread,
                            args=(prev_fg,),
                            daemon=True,
                        ).start()

                self._json(200, {"ok": True, "uri": chosen})
            except Exception as e:
                log.error(f"Erreur {parsed.path} : {e}")
                self._json(500, {"error": str(e)})
        else:
            self.send_response(404)
            self.end_headers()


def run_http_server():
    server = HTTPServer(("127.0.0.1", PORT_HTTP), SpotifyHandler)
    log.info(f"API Spotify sur http://127.0.0.1:{PORT_HTTP}")
    server.serve_forever()


# ═══════════════════════════════════════════════════════
#  SMTC
# ═══════════════════════════════════════════════════════

async def get_thumbnail_smtc(session):
    try:
        props = await session.try_get_media_properties_async()
        if props is None:
            return None
        thumb = getattr(props, "thumbnail", None)
        if thumb is None:
            return None
        stream = await thumb.open_read_async()
        size = stream.size
        if size == 0 or size > 20 * 1024 * 1024:
            return None
        reader = DataReader(stream)
        loaded = await reader.load_async(size)
        if loaded < size:
            return None
        raw = bytes(reader.read_bytes(size))
        if not raw:
            return None
        if raw[:8] == b"\x89PNG\r\n\x1a\n":
            mime = "image/png"
        elif raw[:4] == b"RIFF":
            mime = "image/webp"
        elif raw[:2] == b"\xff\xd8":
            mime = "image/jpeg"
        else:
            mime = "image/jpeg"
        b64 = base64.b64encode(raw).decode("ascii")
        return f"data:{mime};base64,{b64}"
    except Exception as e:
        log.debug(f"SMTC vignette echouee : {e}")
        return None


def get_thumbnail_itunes(title, artist):
    if not title and not artist:
        return None
    try:
        query = urllib.parse.quote(f"{artist} {title}")
        url = f"https://itunes.apple.com/search?term={query}&limit=1&media=music"
        req = urllib.request.Request(url, headers={"User-Agent": "PLATINE/1.0"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode())
            if data.get("resultCount", 0) > 0:
                art = data["results"][0].get("artworkUrl100", "")
                art = art.replace("100x100", "600x600")
                if art:
                    return art
    except Exception as e:
        log.debug(f"iTunes echoue : {e}")
    return None


async def resolve_thumbnail(session, title, artist):
    thumb = await get_thumbnail_smtc(session)
    if thumb:
        return thumb
    return await asyncio.get_event_loop().run_in_executor(
        None, get_thumbnail_itunes, title, artist)


async def broadcast(key, value):
    if value is None:
        return
    msg = f"{key} {value}"
    last_state[key] = value
    dead = set()
    for ws in list(clients):
        try:
            await ws.send(msg)
        except Exception:
            dead.add(ws)
    clients.difference_update(dead)


async def get_active_session(mgr):
    try:
        sessions = mgr.get_sessions()
        for session in sessions:
            try:
                playback = session.get_playback_info()
                if getattr(playback, "playback_status", 0) == 4:
                    props = await session.try_get_media_properties_async()
                    if getattr(props, "title", None):
                        return session
            except Exception:
                continue
        session = mgr.get_current_session()
        if session:
            props = await session.try_get_media_properties_async()
            if getattr(props, "title", None):
                return session
    except Exception as e:
        log.debug(f"Erreur get_active_session : {e}")
    return None


async def poll_loop():
    log.info("Pont SMTC demarre")
    mgr = await GSMTC.request_async()
    prev_track_key = None
    prev_state = None
    prev_pos = -1

    while True:
        try:
            session = await get_active_session(mgr)
            if session is None:
                await asyncio.sleep(0.5)
                continue

            props = await session.try_get_media_properties_async()
            timeline = session.get_timeline_properties()
            playback = session.get_playback_info()

            title = getattr(props, "title", None) or ""
            artist = getattr(props, "artist", None) or ""
            album = getattr(props, "album_title", None) or ""
            source = getattr(props, "source_app_user_model_id", None) or ""
            duration = max(0, timeline.end_time.total_seconds())
            position = max(0, timeline.position.total_seconds())
            playing = getattr(playback, "playback_status", 0) == 4

            track_key = f"{artist}|{title}|{album}"
            if track_key != prev_track_key and title:
                log.info(f"▶ {artist} — {title}")
                prev_track_key = track_key
                await broadcast("TITLE", title)
                await broadcast("ARTIST", artist)
                await broadcast("ALBUM", album)
                await broadcast("PLAYER", source.split(".")[-1] if source else "Inconnu")
                await broadcast("DURATION", int(duration))
                thumb = await resolve_thumbnail(session, title, artist)
                if thumb:
                    await broadcast("COVER", thumb)

            if playing != prev_state:
                await broadcast("STATE", "1" if playing else "0")
                prev_state = playing

            if abs(position - prev_pos) > 1.0:
                await broadcast("POSITION", int(position))
                prev_pos = position

        except Exception as e:
            log.debug(f"Erreur polling : {e}")
        await asyncio.sleep(0.3)


async def command_handler(ws, message):
    try:
        parts = message.strip().split(" ", 1)
        cmd = parts[0].upper()
        arg = parts[1] if len(parts) > 1 else None

        mgr = await GSMTC.request_async()
        session = await get_active_session(mgr)
        if session is None:
            return

        if cmd == "PLAYPAUSE":
            status = session.get_playback_info().playback_status
            if status == 4:
                await session.try_pause_async()
            else:
                await session.try_play_async()
        elif cmd == "NEXT":
            await session.try_skip_next_async()
            await asyncio.sleep(0.8)
        elif cmd == "PREVIOUS":
            await session.try_skip_previous_async()
            await asyncio.sleep(0.8)
        elif cmd == "SETPOSITION" and arg:
            await session.try_change_playback_position_async(float(arg))
        elif cmd == "STOP":
            await session.try_stop_async()
    except Exception as e:
        log.debug(f"Commande echouee : {message} -> {e}")


async def ws_handler(ws):
    log.info(f"Client connecte : {ws.remote_address}")
    clients.add(ws)
    try:
        for k, v in last_state.items():
            await ws.send(f"{k} {v}")
        async for msg in ws:
            await command_handler(ws, msg)
    finally:
        clients.discard(ws)


# ═══════════════════════════════════════════════════════
#  DEMARRAGE
# ═══════════════════════════════════════════════════════

async def main():
    global MAIN_LOOP
    MAIN_LOOP = asyncio.get_running_loop()
    try:
        await websockets.serve(ws_handler, "127.0.0.1", PORT_WS)
    except OSError:
        try:
            async with websockets.connect(f"ws://127.0.0.1:{PORT_WS}", open_timeout=2):
                log.info("Un bridge PLATINE tourne deja. Fermeture.")
                return
        except Exception:
            log.error(f"Port {PORT_WS} occupe.")
            return
    log.info(f"WebSocket SMTC sur ws://127.0.0.1:{PORT_WS}")

    threading.Thread(target=run_http_server, daemon=True).start()
    init_spotify()
    await poll_loop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Arret.")