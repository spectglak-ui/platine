"""
PLATINE Bridge v4 — pont SMTC vers WebSocket
Correction : selection intelligente de la session qui joue vraiment.
"""
import asyncio
import base64
import json
import logging
import urllib.request
import urllib.parse
from ctypes import cast, POINTER

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("platine-bridge")

try:
    from winsdk.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as GSMTC,
    )
    from winsdk.windows.storage.streams import DataReader, Buffer, InputStreamOptions
    import websockets
except ImportError as e:
    log.critical(f"Module manquant : {e}\nLancez : pip install winsdk websockets")
    raise SystemExit(1)

PORT = 8974
clients: set = set()
last_state: dict = {}


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
        log.debug(f"Vignette iTunes echouee : {e}")
    return None


async def resolve_thumbnail(session, title, artist):
    thumb = await get_thumbnail_smtc(session)
    if thumb:
        return thumb
    thumb = await asyncio.get_event_loop().run_in_executor(
        None, get_thumbnail_itunes, title, artist
    )
    return thumb


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


# ═══════════════════════════════════════════════════════
#  SELECTION INTELLIGENTE DE LA SESSION QUI JOUE
# ═══════════════════════════════════════════════════════

async def get_active_session(mgr):
    """
    Parcourt TOUTES les sessions SMTC et retourne celle qui est en lecture.
    Si aucune ne joue, retourne la session actuelle (dernière active).
    """
    try:
        # Methode 1 : iterer sur toutes les sessions pour trouver celle qui joue
        sessions = mgr.get_sessions()
        for session in sessions:
            try:
                playback = session.get_playback_info()
                status = getattr(playback, "playback_status", 0)
                if status == 4:  # Playing
                    # Verifier qu'il y a bien des metadonnees (evite les sessions fantomes)
                    props = await session.try_get_media_properties_async()
                    title = getattr(props, "title", None)
                    if title:
                        return session
            except Exception:
                continue

        # Methode 2 : fallback sur la session "courante"
        session = mgr.get_current_session()
        if session:
            props = await session.try_get_media_properties_async()
            title = getattr(props, "title", None)
            if title:
                return session
    except Exception as e:
        log.debug(f"Erreur get_active_session : {e}")

    return None


async def poll_loop():
    log.info("Pont PLATINE demarre — en attente d'un lecteur...")
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


async def main():
    try:
        await websockets.serve(ws_handler, "127.0.0.1", PORT)
    except OSError:
        try:
            async with websockets.connect(f"ws://127.0.0.1:{PORT}", open_timeout=2):
                log.info("Un bridge PLATINE tourne deja.")
                return
        except Exception:
            log.error(f"Port {PORT} occupe.")
            return
    log.info(f"WebSocket actif sur ws://127.0.0.1:{PORT}")
    await poll_loop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Arret demande.")