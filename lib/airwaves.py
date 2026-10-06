#!/usr/bin/env python3
"""Ad-free internet radio for the grivera.airwaves Omarchy plugin.

Every station comes from a listener-supported, commercial-free broadcaster:
SomaFM, Radio Paradise, NTS and Radio France's FIP, plus any streams you add
in ~/.config/grivera-airwaves/stations.json. Playback runs in mpv. With
mpv-mpris installed, media keys and the Omarchy media OSD treat it like any
other player, and next/previous step through the stations.

Standard library only.

  airwaves status [--json]       what's on
  airwaves toggle | stop | next | prev
  airwaves play [station]        resume, or play the closest name match
  airwaves like                  save the current song
  airwaves volume <n|+n|-n>
  airwaves sleep <minutes|off>
  airwaves stations              list every station
  airwaves daemon                JSON state lines on stdout, commands on stdin
"""

import concurrent.futures
import gzip
import hashlib
import html
import json
import os
import queue
import re
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request

HOME = os.path.expanduser("~")
STATE_DIR = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.join(HOME, ".local/state"), "grivera-airwaves")
CACHE_DIR = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.join(HOME, ".cache"), "grivera-airwaves")
USER_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.join(HOME, ".config"), "grivera-airwaves")
RUN_DIR = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "grivera-airwaves")
CONFIG_FILE = os.path.join(STATE_DIR, "config.json")
LIKED_FILE = os.path.join(STATE_DIR, "liked.json")
HISTORY_FILE = os.path.join(STATE_DIR, "history.json")
CUSTOM_FILE = os.path.join(USER_DIR, "stations.json")
ART_DIR = os.path.join(CACHE_DIR, "art")
CATALOG_CACHE = os.path.join(CACHE_DIR, "catalog.json")
MPV_SOCK = os.path.join(RUN_DIR, "mpv.sock")
CTL_SOCK = os.path.join(RUN_DIR, "ctl.sock")
QUEUE_FILE = os.path.join(RUN_DIR, "queue.m3u")
LIB = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(os.path.dirname(LIB), "assets")
UA = "grivera-airwaves/1.0 (+https://github.com/grivera82)"

NETWORKS = [
    {"id": "soma", "name": "SomaFM", "short": "SomaFM", "color": "#ef5a3c",
     "about": "Listener-supported, commercial-free radio from San Francisco since 2000. Over 40 hand-programmed channels.",
     "support": "https://somafm.com/support/"},
    {"id": "rp", "name": "Radio Paradise", "short": "Paradise", "color": "#3f95e0",
     "about": "Eclectic, human-curated, listener-supported radio from California. No ads, ever.",
     "support": "https://radioparadise.com/support"},
    {"id": "nts", "name": "NTS Radio", "short": "NTS", "color": "#9a9aa2",
     "about": "Independent radio from London: two live channels of guest DJs, plus endless themed mixtapes.",
     "support": "https://www.nts.live/supporters"},
    {"id": "fip", "name": "FIP", "short": "FIP", "color": "#e2167f",
     "about": "Radio France's legendary eclectic station and its themed webradios. Public service, no ads.",
     "support": "https://www.radiofrance.fr/fip"},
    {"id": "custom", "name": "My stations", "short": "Mine", "color": "",
     "about": "Streams you added. Edit ~/.config/grivera-airwaves/stations.json or use Settings.", "support": ""},
]
NET_BY_ID = {n["id"]: n for n in NETWORKS}

# (channel, name, stream, low-bitrate stream, genre, description)
RP_CHANNELS = [
    (0, "Main Mix", "aac-320", "aac-128", "eclectic", "Rock, world, electronica, jazz and more, hand-blended into one seamless mix."),
    (1, "Mellow Mix", "mellow-320", "mellow-128", "mellow", "The gentler side of the Main Mix: soothing, soulful, never sleepy."),
    (2, "Rock Mix", "rock-320", "rock-128", "rock", "The heavier side of Paradise: classic and modern rock with an eclectic edge."),
    (3, "Global Mix", "global-320", "global-128", "world", "Music from every corner of the planet, mixed for curious ears."),
    (5, "Beyond…", "beyond-320", "beyond-128", "experimental", "Adventurous, genre-bending sounds from the outer edges."),
    (42, "Serenity", "serenity", "serenity", "ambient", "Ambient soundscapes and nature recordings for calm and focus."),
    (945, "KFAT", "kfat-320", "kfat-128", "americana", "Outlaw country, folk and bluegrass in the spirit of the legendary Gilroy station."),
]
RP_STREAM = "https://stream.radioparadise.com/"
RP_ART = "https://img.radioparadise.com/channels/0/%d/cover_512x512/0.jpg"

# (livemeta station id, stream slug, name, genre, description)
FIP_CHANNELS = [
    (7, "fip", "FIP", "eclectic", "The original: jazz, chanson, rock, world and electro, segued with Parisian flair."),
    (64, "fiprock", "FIP Rock", "rock", "Rock from every era, from garage to post-rock."),
    (65, "fipjazz", "FIP Jazz", "jazz", "Jazz in all its forms, from swing and bebop to today's scene."),
    (66, "fipgroove", "FIP Groove", "soul / funk", "Soul, funk, hip-hop and everything that makes you move."),
    (69, "fipworld", "FIP Monde", "world", "World music without borders."),
    (70, "fipnouveautes", "FIP Nouveautés", "new music", "Brand-new releases, picked by FIP's programmers."),
    (71, "fipreggae", "FIP Reggae", "reggae", "Roots, dub, dancehall and ska."),
    (74, "fipelectro", "FIP Electro", "electronic", "Electronic music from ambient to the dancefloor."),
    (77, "fipmetal", "FIP Metal", "metal", "Heavy, doom, black, prog and more."),
]
FIP_STREAM = "https://icecast.radiofrance.fr/"
FIP_META = "https://api.radiofrance.fr/livemeta/pull/%d"

NTS_LIVE = [("1", "NTS 1", "https://stream-relay-geo.ntslive.net/stream"),
            ("2", "NTS 2", "https://stream-relay-geo.ntslive.net/stream2")]
NTS_API = "https://www.nts.live/api/v2/"

DEFAULT_CONFIG = {
    "volume": 70,
    "favorites": ["soma:groovesalad", "rp:0", "fip:65", "nts:live1"],
    "last": "",
    "quality": "high",          # high | low
    "visualizer": True,         # live level bars in the bar
    "barTitle": True,           # song title next to the bar icon
    "barTitleWidth": 180,
    "notify": False,            # notification on every song change
    "lookupArt": True,          # album art from the iTunes Search API
    "search": "youtube",        # youtube | spotify | apple
    "resume": True,             # resume after login if the radio was on
    "wasPlaying": False,
    "sleepAt": 0,               # survives shell reloads
}

# What SomaFM and Radio Paradise put in the stream title between songs.
STATION_ID = re.compile(r"somafm|radio paradise|commercial-free|listener-supported", re.I)

TICK = 1.0
LEVEL_HZ = 20


# ---------------------------------------------------------------- helpers

def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, data, indent=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = "%s.%d.tmp" % (path, threading.get_ident())
    with open(tmp, "w") as f:
        json.dump(data, f, indent=indent, ensure_ascii=False, separators=None if indent else (",", ":"))
    os.replace(tmp, path)


def http_get(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
        ctype = r.headers.get("Content-Type", "")
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return data, ctype


def http_json(url, timeout=10):
    return json.loads(http_get(url, timeout)[0])


def clean(s):
    return re.sub(r"\s+", " ", html.unescape(str(s or ""))).strip()


def split_icy(title):
    """'Artist - Title' -> (artist, title). Station IDs and blanks -> ('', '')."""
    t = clean(title)
    if not t:
        return "", ""
    for sep in (" - ", " – ", " — "):
        if sep in t:
            a, b = t.split(sep, 1)
            return a.strip(), b.strip()
    return "", t


def track_key(artist, title):
    return re.sub(r"[^a-z0-9]+", " ", ("%s|%s" % (artist, title)).lower()).strip()


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "station"


def open_url(url):
    for cmd in (["omarchy-launch-webapp", url], ["xdg-open", url]):
        if shutil.which(cmd[0]):
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            return True
    return False


def copy_text(text):
    if not shutil.which("wl-copy"):
        return False
    # Text goes in on stdin, never on the command line.
    p = subprocess.Popen(["wl-copy"], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    p.communicate(text.encode())
    return p.returncode == 0


def search_url(service, artist, title):
    q = " ".join(x for x in (artist, title) if x)
    if service == "spotify":
        return "https://open.spotify.com/search/" + urllib.parse.quote(q)
    if service == "apple":
        return "https://music.apple.com/search?term=" + urllib.parse.quote_plus(q)
    return "https://music.youtube.com/search?q=" + urllib.parse.quote_plus(q)


def mpris_script():
    for d in (os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.join(HOME, ".config"), "mpv/scripts"),
              "/etc/mpv/scripts", "/usr/lib/mpv-mpris", "/usr/lib/mpv"):
        p = os.path.join(d, "mpris.so")
        if os.path.exists(p):
            return p
    return ""


# ---------------------------------------------------------------- art cache

class ArtCache:
    """Downloads cover art and logos into ~/.cache so QML loads local files."""

    def __init__(self, on_done):
        self.on_done = on_done
        self.pending = set()
        self.failed = {}
        self.lock = threading.Lock()
        self.pool = concurrent.futures.ThreadPoolExecutor(4)
        os.makedirs(ART_DIR, exist_ok=True)
        self.prune()

    @staticmethod
    def path(url):
        return os.path.join(ART_DIR, hashlib.sha1(url.encode()).hexdigest()[:24])

    def get(self, url):
        if not url:
            return ""
        if url.startswith("/"):
            return url if os.path.exists(url) else ""
        p = self.path(url)
        if os.path.exists(p):
            return p
        with self.lock:
            if url in self.pending or time.time() - self.failed.get(url, 0) < 600:
                return ""
            self.pending.add(url)
        self.pool.submit(self.fetch, url)
        return ""

    def fetch(self, url):
        ok = False
        try:
            data, ctype = http_get(url, timeout=15)
            if data and (ctype.startswith("image/") or data[:4] in (b"\x89PNG", b"RIFF") or data[:3] == b"\xff\xd8\xff"):
                p = self.path(url)
                with open(p + ".tmp", "wb") as f:
                    f.write(data)
                os.replace(p + ".tmp", p)
                ok = True
        except Exception:
            pass
        with self.lock:
            self.pending.discard(url)
            if not ok:
                self.failed[url] = time.time()
        if ok:
            self.on_done()

    def prune(self, keep=800):
        try:
            files = [os.path.join(ART_DIR, f) for f in os.listdir(ART_DIR)]
            if len(files) <= keep:
                return
            files.sort(key=lambda p: os.path.getatime(p))
            for p in files[:len(files) - keep]:
                os.remove(p)
        except OSError:
            pass


class ArtLookup:
    """Album art for songs whose station doesn't send any (iTunes Search API, no key)."""

    def __init__(self):
        self.mem = {}
        self.lock = threading.Lock()

    def find(self, artist, title):
        key = track_key(artist, title)
        with self.lock:
            if key in self.mem:
                return self.mem[key]
        res = None
        try:
            q = urllib.parse.urlencode({"term": "%s %s" % (artist, title), "media": "music", "entity": "song", "limit": 5})
            data = http_json("https://itunes.apple.com/search?" + q, timeout=8)
            want = artist.lower().split(" feat")[0].split(" & ")[0].strip()
            for r in data.get("results", []):
                name = (r.get("artistName") or "").lower()
                if want and want[:12] not in name and name[:12] not in want:
                    continue
                art = (r.get("artworkUrl100") or "").replace("100x100bb", "600x600bb")
                if art:
                    res = {"art": art, "album": r.get("collectionName") or "",
                           "year": (r.get("releaseDate") or "")[:4]}
                    break
        except Exception:
            return None  # network trouble: try again next time
        with self.lock:
            if len(self.mem) > 600:
                self.mem.clear()
            self.mem[key] = res
        return res


# ---------------------------------------------------------------- catalog

class Catalog:
    def __init__(self):
        self.lock = threading.RLock()
        self.stations = {}
        self.order = []
        self.cached = load_json(CATALOG_CACHE, {})
        self.custom_mtime = None
        self.build()

    def add(self, st):
        st.setdefault("genre", "")
        st.setdefault("desc", "")
        st.setdefault("art", "")
        st.setdefault("listeners", 0)
        st.setdefault("now", None)
        st.setdefault("icy", False)
        st.setdefault("urlLow", st["url"])
        self.stations[st["id"]] = st
        self.order.append(st["id"])

    def build(self):
        with self.lock:
            old = self.stations
            self.stations, self.order = {}, []
            for c in sorted(self.cached.get("soma", []), key=lambda c: c["title"].lower()):
                self.add({"id": "soma:" + c["id"], "net": "soma", "name": c["title"], "genre": c.get("genre", "").replace("|", " / "),
                          "desc": c.get("description", ""), "art": c.get("xlimage") or c.get("largeimage") or c.get("image", ""),
                          "url": "https://ice2.somafm.com/%s-128-aac" % c["id"],
                          "urlLow": "https://ice2.somafm.com/%s-64-aac" % c["id"],
                          "listeners": int(c.get("listeners") or 0), "icy": True,
                          "now": self.icy_now(c.get("lastPlaying"))})
            for chan, name, s, low, genre, desc in RP_CHANNELS:
                self.add({"id": "rp:%d" % chan, "net": "rp", "name": name, "genre": genre, "desc": desc,
                          "art": RP_ART % chan, "url": RP_STREAM + s, "urlLow": RP_STREAM + low, "icy": True, "rp": chan,
                          "listeners": int(self.cached.get("rpListeners", {}).get(str(chan), 0))})
            for ch, name, url in NTS_LIVE:
                self.add({"id": "nts:live" + ch, "net": "nts", "name": name, "genre": "live",
                          "desc": "Live from NTS: a different resident or guest every hour or two.", "url": url, "nts": ch})
            for m in self.cached.get("ntsMixtapes", []):
                self.add({"id": "nts:" + m["alias"], "net": "nts", "name": m["title"], "genre": "infinite mixtape",
                          "desc": m["subtitle"], "art": m["art"], "url": m["url"]})
            for sid, s, name, genre, desc in FIP_CHANNELS:
                self.add({"id": "fip:%d" % sid, "net": "fip", "name": name, "genre": genre, "desc": desc,
                          "url": FIP_STREAM + s + "-hifi.aac", "urlLow": FIP_STREAM + s + "-midfi.mp3", "fip": sid})
            for c in self.load_custom():
                self.add(c)
            # Keep live data (now playing, art) across rebuilds.
            for sid, st in self.stations.items():
                o = old.get(sid)
                if o:
                    if st["now"] is None:
                        st["now"] = o.get("now")
                    if st["net"] == "nts" and o.get("art"):
                        st["art"] = st["art"] or o["art"]

    @staticmethod
    def icy_now(text):
        a, t = split_icy(text)
        return {"artist": a, "title": t} if t else None

    def load_custom(self):
        try:
            self.custom_mtime = os.path.getmtime(CUSTOM_FILE)
        except OSError:
            self.custom_mtime = None
            return []
        out, seen = [], set()
        data = load_json(CUSTOM_FILE, [])
        for c in data if isinstance(data, list) else data.get("stations", []):
            if not isinstance(c, dict) or not str(c.get("url", "")).startswith(("http://", "https://")):
                continue
            name = clean(c.get("name")) or c["url"]
            sid = "custom:" + slug(name)
            while sid in seen:
                sid += "-"
            seen.add(sid)
            out.append({"id": sid, "net": "custom", "name": name, "genre": clean(c.get("genre")),
                        "desc": clean(c.get("description")), "art": c.get("image", ""), "url": c["url"], "icy": True})
        return out

    def custom_changed(self):
        try:
            m = os.path.getmtime(CUSTOM_FILE)
        except OSError:
            m = None
        return m != self.custom_mtime

    def save_custom(self, entries):
        save_json(CUSTOM_FILE, entries, indent=2)

    def get(self, sid):
        with self.lock:
            return self.stations.get(sid)

    def by_url(self, url):
        with self.lock:
            for st in self.stations.values():
                if url in (st["url"], st["urlLow"]):
                    return st
        return None

    def ids(self, net=None):
        with self.lock:
            return [i for i in self.order if net is None or self.stations[i]["net"] == net]

    def find(self, query):
        q = query.lower().strip()
        if not q:
            return None
        with self.lock:
            best, score = None, 0
            for sid in self.order:
                st = self.stations[sid]
                name = st["name"].lower()
                s = 100 if name == q or sid == q else 80 if name.startswith(q) else 60 if q in name \
                    else 30 if q in st["genre"].lower() else 20 if q in st["desc"].lower() else 0
                if s > score:
                    best, score = sid, s
            return best

    # -- network fetchers (run on the pool) --

    def fetch_soma(self):
        data = http_json("https://somafm.com/channels.json")
        chans = [c for c in data.get("channels", []) if c.get("id") and c.get("title")]
        if chans:
            self.cached["soma"] = chans
            self.persist()
            self.build()

    def fetch_rp_listeners(self):
        data = http_json("https://api.radioparadise.com/api/list_chan")
        self.cached["rpListeners"] = {str(c["chan"]): int(c.get("current_listeners") or 0) for c in data}
        self.persist()
        with self.lock:
            for c in data:
                st = self.stations.get("rp:%s" % c["chan"])
                if st:
                    st["listeners"] = int(c.get("current_listeners") or 0)

    @staticmethod
    def rp_now(chan):
        d = http_json("https://api.radioparadise.com/api/now_playing?chan=%d" % chan)
        year = str(d.get("year") or "")
        return {"artist": clean(d.get("artist")), "title": clean(d.get("title")), "album": clean(d.get("album")),
                "year": "" if year == "0" else year, "art": d.get("cover") or ""}

    def fetch_rp_now(self):
        for chan, *_ in RP_CHANNELS:
            try:
                now = self.rp_now(chan)
            except Exception:
                continue
            with self.lock:
                st = self.stations.get("rp:%d" % chan)
                if st:
                    st["now"] = now

    @staticmethod
    def fip_now(sid):
        d = http_json(FIP_META % sid)
        steps = d.get("steps") or {}
        now = time.time()
        live = [s for s in steps.values() if s.get("start", 0) <= now < s.get("end", 0)]
        songs = [s for s in live if s.get("embedType") == "song"]
        if songs:
            s = songs[0]
            return {"artist": clean(s.get("authors") or s.get("performers")), "title": clean(s.get("title")),
                    "album": clean(s.get("titreAlbum")), "year": str(s.get("anneeEditionMusique") or ""),
                    "art": s.get("visual") or "", "ends": s.get("end", 0)}
        shows = sorted(live, key=lambda s: -s.get("depth", 0))
        if shows:
            s = shows[0]
            return {"artist": "", "title": clean(s.get("title")), "show": True, "ends": s.get("end", 0)}
        return None

    def fetch_fip_now(self):
        for sid, *_ in FIP_CHANNELS:
            try:
                now = self.fip_now(sid)
            except Exception:
                continue
            with self.lock:
                st = self.stations.get("fip:%d" % sid)
                if st:
                    st["now"] = now

    def fetch_nts_live(self):
        data = http_json(NTS_API + "live")
        for r in data.get("results", []):
            now = r.get("now") or {}
            det = (now.get("embeds") or {}).get("details") or {}
            media = det.get("media") or {}
            nxt = (r.get("next") or {}).get("broadcast_title")
            genres = [clean(g.get("value")) for g in det.get("genres") or []][:3]
            info = {"artist": clean(det.get("location_long")), "title": clean(now.get("broadcast_title")),
                    "show": True, "genres": genres, "next": clean(nxt),
                    "art": media.get("picture_medium_large") or media.get("background_medium_large") or ""}
            with self.lock:
                st = self.stations.get("nts:live%s" % r.get("channel_name"))
                if st:
                    st["now"] = info
                    st["art"] = info["art"] or st["art"]
                    st["genre"] = ", ".join(g.lower() for g in genres) or "live"

    def fetch_nts_mixtapes(self):
        data = http_json(NTS_API + "mixtapes")
        mixes = []
        for m in data.get("results", []):
            if m.get("mixtape_alias") and m.get("audio_stream_endpoint"):
                mixes.append({"alias": m["mixtape_alias"], "title": clean(m.get("title")), "subtitle": clean(m.get("subtitle")),
                              "url": m["audio_stream_endpoint"], "art": (m.get("media") or {}).get("picture_medium", "")})
        if mixes:
            self.cached["ntsMixtapes"] = mixes
            self.persist()
            self.build()

    def persist(self):
        try:
            save_json(CATALOG_CACHE, self.cached)
        except OSError:
            pass


# ---------------------------------------------------------------- mpv

class Mpv:
    """JSON IPC client for one mpv process."""

    def __init__(self, path, on_event, on_close):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(path)
        self.on_event = on_event
        self.on_close = on_close
        self.wlock = threading.Lock()
        self.waiting = {}
        self.serial = 0
        self.alive = True
        # Events are handled off the reader thread so handlers can call
        # command() without waiting on a reply only the reader can deliver.
        self.events = queue.Queue()
        threading.Thread(target=self.reader, daemon=True).start()
        threading.Thread(target=self.dispatch, daemon=True).start()

    def dispatch(self):
        while True:
            msg = self.events.get()
            if msg is None:
                break
            try:
                self.on_event(msg)
            except Exception as exc:
                sys.stderr.write("airwaves: event handler: %r\n" % exc)
        self.on_close(self)

    def reader(self):
        buf = b""
        try:
            while True:
                chunk = self.sock.recv(65536)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    try:
                        msg = json.loads(line)
                    except ValueError:
                        continue
                    rid = msg.get("request_id")
                    if rid and rid in self.waiting:
                        slot = self.waiting.pop(rid)
                        slot[1] = msg
                        slot[0].set()
                    elif "event" in msg:
                        self.events.put(msg)
        except OSError:
            pass
        self.alive = False
        for slot in list(self.waiting.values()):
            slot[0].set()
        self.events.put(None)

    def command(self, *args, timeout=4):
        if not self.alive:
            raise OSError("mpv is gone")
        with self.wlock:
            self.serial += 1
            rid = self.serial
            slot = [threading.Event(), None]
            self.waiting[rid] = slot
            self.sock.sendall((json.dumps({"command": list(args), "request_id": rid}) + "\n").encode())
        if not slot[0].wait(timeout):
            self.waiting.pop(rid, None)
            raise OSError("mpv timed out on %s" % args[0])
        msg = slot[1] or {}
        if msg.get("error") not in ("success", None):
            raise OSError("mpv %s: %s" % (args[0], msg.get("error")))
        return msg.get("data")

    def get(self, prop, default=None):
        try:
            return self.command("get_property", prop)
        except OSError:
            return default

    def set(self, prop, value):
        return self.command("set_property", prop, value)

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


OBSERVED = ["pause", "playlist-pos", "metadata", "volume", "mute", "paused-for-cache", "core-idle", "audio-bitrate",
            "audio-codec-name"]


# ---------------------------------------------------------------- notifications
#
# Notifications go straight to the notification server over the session bus
# rather than through notify-send, so nothing shows up on a command line.

DBUS_ALIGN = {"y": 1, "b": 4, "i": 4, "u": 4, "x": 8, "t": 8, "d": 8,
              "s": 4, "o": 4, "g": 1, "v": 1, "a": 4, "(": 8, "{": 8}
DBUS_FIXED = {"y": "B", "b": "I", "i": "i", "u": "I", "x": "q", "t": "Q", "d": "d"}


def dbus_types(sig):
    """Split a signature into its complete types: "sa{sv}i" -> s, a{sv}, i."""
    out, i = [], 0
    while i < len(sig):
        j = i
        while sig[j] == "a":
            j += 1
        if sig[j] in "({":
            depth = 0
            while True:
                depth += sig[j] in "({"
                depth -= sig[j] in ")}"
                j += 1
                if not depth:
                    break
        else:
            j += 1
        out.append(sig[i:j])
        i = j
    return out


def dbus_pad(buf, n):
    buf.extend(b"\0" * (-len(buf) % n))


def dbus_write(buf, sig, val):
    """Append one value of complete type `sig`; variants are (signature, value)."""
    c = sig[0]
    if c in DBUS_FIXED:
        dbus_pad(buf, DBUS_ALIGN[c])
        buf.extend(struct.pack("<" + DBUS_FIXED[c], val))
    elif c in "so":
        raw = val.encode()
        dbus_pad(buf, 4)
        buf.extend(struct.pack("<I", len(raw)) + raw + b"\0")
    elif c == "g":
        buf.extend(bytes([len(val)]) + val.encode() + b"\0")
    elif c == "v":
        dbus_write(buf, "g", val[0])
        dbus_write(buf, val[0], val[1])
    elif c == "a":
        dbus_pad(buf, 4)
        at = len(buf)
        buf.extend(b"\0\0\0\0")
        dbus_pad(buf, DBUS_ALIGN[sig[1]])
        start = len(buf)
        for item in (val.items() if sig[1] == "{" else val):
            dbus_write(buf, sig[1:], item)
        struct.pack_into("<I", buf, at, len(buf) - start)
    else:
        dbus_pad(buf, 8)
        for t, v in zip(dbus_types(sig[1:-1]), val):
            dbus_write(buf, t, v)


def dbus_read(data, pos, sig, end="<"):
    """One value of complete type `sig` at `pos` -> (value, new pos)."""
    c = sig[0]
    pos += -pos % DBUS_ALIGN[c]
    if c in DBUS_FIXED:
        fmt = end + DBUS_FIXED[c]
        return struct.unpack_from(fmt, data, pos)[0], pos + struct.calcsize(fmt)
    if c in "so":
        n = struct.unpack_from(end + "I", data, pos)[0]
        return data[pos + 4:pos + 4 + n].decode("utf-8", "replace"), pos + 5 + n
    if c == "g":
        n = data[pos]
        return data[pos + 1:pos + 1 + n].decode(), pos + 2 + n
    if c == "v":
        inner, pos = dbus_read(data, pos, "g", end)
        return dbus_read(data, pos, inner, end)
    if c == "a":
        n = struct.unpack_from(end + "I", data, pos)[0]
        pos += 4
        pos += -pos % DBUS_ALIGN[sig[1]]
        stop, items = pos + n, []
        while pos < stop:
            item, pos = dbus_read(data, pos, sig[1:], end)
            items.append(item)
        return (dict(items) if sig[1] == "{" else items), pos
    vals = []
    for t in dbus_types(sig[1:-1]):
        v, pos = dbus_read(data, pos, t, end)
        vals.append(v)
    return tuple(vals), pos


class SessionBus:
    """Just enough of the D-Bus wire protocol to call methods and hear signals."""

    def __init__(self, match, on_signal):
        self.match = match              # AddMatch rule for the signals we want
        self.on_signal = on_signal      # (interface, member, args)
        self.sock = None
        self.serial = 0
        self.pending = {}               # serial -> [Event, reply args, error name]
        self.lock = threading.RLock()   # connect() calls Hello while holding it

    def connect(self):
        addrs = os.environ.get("DBUS_SESSION_BUS_ADDRESS") or \
            "unix:path=%s/bus" % (os.environ.get("XDG_RUNTIME_DIR") or "/run/user/%d" % os.getuid())
        for addr in addrs.split(";"):
            kind, _, rest = addr.partition(":")
            opts = dict(kv.split("=", 1) for kv in rest.split(",") if "=" in kv)
            if kind != "unix" or not ("path" in opts or "abstract" in opts):
                continue
            path = opts.get("path") or "\0" + opts["abstract"]
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(5)
            try:
                sock.connect(path)
                sock.sendall(b"\0AUTH EXTERNAL " + str(os.getuid()).encode().hex().encode() + b"\r\n")
                reply = b""
                while not reply.endswith(b"\r\n"):
                    chunk = sock.recv(256)
                    if not chunk:
                        raise OSError("bus closed during auth")
                    reply += chunk
                if not reply.startswith(b"OK"):
                    raise OSError("bus refused auth")
                sock.sendall(b"BEGIN\r\n")
            except OSError:
                sock.close()
                continue
            sock.settimeout(None)
            self.sock = sock
            threading.Thread(target=self.reader, args=(sock,), daemon=True).start()
            try:
                for member, sig, args in (("Hello", "", ()), ("AddMatch", "s", [self.match])):
                    self.call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                              member, sig, args)
            except OSError:
                self.drop()
                raise
            return
        raise OSError("no session bus")

    def call(self, dest, path, iface, member, sig="", args=(), reply=True):
        body = bytearray()
        for t, v in zip(dbus_types(sig), args):
            dbus_write(body, t, v)
        fields = [(1, ("o", path)), (2, ("s", iface)), (3, ("s", member)), (6, ("s", dest))]
        if sig:
            fields.append((8, ("g", sig)))
        with self.lock:
            if self.sock is None:
                self.connect()
            self.serial += 1
            serial = self.serial
            msg = bytearray(struct.pack("<cBBBII", b"l", 1, 0 if reply else 1, 1, len(body), serial))
            dbus_write(msg, "a(yv)", fields)
            dbus_pad(msg, 8)
            waiter = self.pending[serial] = [threading.Event(), None, None] if reply else None
            try:
                self.sock.sendall(msg + body)
            except OSError:
                self.drop()
                raise
        if not reply:
            return None
        if not waiter[0].wait(5):
            self.pending.pop(serial, None)
            raise OSError("%s timed out" % member)
        if waiter[2]:
            raise OSError(waiter[2])
        return waiter[1]

    def drop(self):
        sock, self.sock = self.sock, None
        if sock:
            sock.close()
        for waiter in self.pending.values():
            if waiter:
                waiter[2] = "bus connection lost"
                waiter[0].set()
        self.pending.clear()

    def reader(self, sock):
        buf = b""

        def need(n):
            nonlocal buf
            while len(buf) < n:
                chunk = sock.recv(65536)
                if not chunk:
                    raise OSError("bus closed")
                buf += chunk

        try:
            while True:
                need(16)
                end = "<" if buf[:1] == b"l" else ">"
                kind = buf[1]
                body_len, _, fields_len = struct.unpack_from(end + "III", buf, 4)
                start = 16 + fields_len + (-fields_len % 8)
                need(start + body_len)
                raw, buf = buf[:start + body_len], buf[start + body_len:]
                fields = dict(dbus_read(raw, 12, "a(yv)", end)[0])
                args, pos = [], start
                for t in dbus_types(fields.get(8, "")):
                    v, pos = dbus_read(raw, pos, t, end)
                    args.append(v)
                if kind in (2, 3):          # method return, error
                    waiter = self.pending.pop(fields.get(5), None)
                    if waiter:
                        waiter[1], waiter[2] = args, (fields.get(4) if kind == 3 else None)
                        waiter[0].set()
                elif kind == 4:             # signal
                    self.on_signal(fields.get(2), fields.get(3), args)
        except (OSError, struct.error, ValueError, IndexError):
            with self.lock:
                if self.sock is sock:
                    self.drop()


class Notifier:
    DEST = "org.freedesktop.Notifications"
    PATH = "/org/freedesktop/Notifications"

    def __init__(self, on_action):
        self.on_action = on_action      # (tag, action key)
        self.bus = SessionBus("type='signal',interface='%s'" % self.DEST, self.on_signal)
        self.ids = {}                   # tag -> notification id, so updates replace
        self.tags = {}                  # notification id -> tag
        self.lock = threading.Lock()

    def send(self, tag, summary, body, icon="", actions=(), slot=None):
        """`slot` names a notification to replace in place (one per song change)."""
        slot = slot or tag

        def run():
            with self.lock:
                try:
                    nid = self.bus.call(self.DEST, self.PATH, self.DEST, "Notify", "susssasa{sv}i",
                                        ["Airwaves", self.ids.get(slot, 0), icon or os.path.join(ASSETS, "airwaves.svg"),
                                         summary, body, list(actions), {"x-grivera-airwaves": ("s", tag)}, -1])[0]
                except (OSError, IndexError):
                    return
                self.ids[slot] = nid
                self.tags[nid] = tag
        threading.Thread(target=run, daemon=True).start()

    def on_signal(self, iface, member, args):
        if iface != self.DEST or not args:
            return
        if member == "ActionInvoked" and len(args) > 1:
            tag = self.tags.get(args[0])
            if tag:
                threading.Thread(target=self.on_action, args=(tag, args[1]), daemon=True).start()
        elif member == "NotificationClosed":
            self.tags.pop(args[0], None)
            for slot, nid in list(self.ids.items()):
                if nid == args[0]:
                    del self.ids[slot]


# ---------------------------------------------------------------- engine

class Engine:
    def __init__(self, emit=None):
        self.emit = emit or (lambda o: None)
        self.lock = threading.RLock()
        self.wake = threading.Event()
        cfg = load_json(CONFIG_FILE, {})
        self.config = dict(DEFAULT_CONFIG)
        self.config.update(cfg if isinstance(cfg, dict) else {})
        self.liked = load_json(LIKED_FILE, [])
        self.history = load_json(HISTORY_FILE, [])
        self.catalog = Catalog()
        self.art = ArtCache(self.changed)
        self.lookup = ArtLookup()
        self.pool = concurrent.futures.ThreadPoolExecutor(6)
        self.mpv = None
        self.mpv_props = {}
        self.queue = []
        self.station_id = ""
        self.track = None
        self.extra = {}           # api info for the current track: art, album, year
        self.error = ""
        self.error_at = 0
        self.failures = 0
        self.paused_at = 0
        self.sleep_at = self.config["sleepAt"] if self.config["sleepAt"] > time.time() else 0
        self.fading = False
        self.panel_open = False
        self.due = {}
        self.last_run = {}
        self.busy = set()
        self.notifier = Notifier(self.on_notification_action)
        os.makedirs(RUN_DIR, mode=0o700, exist_ok=True)

    # -- plumbing --

    def changed(self):
        self.wake.set()

    def save_config(self):
        try:
            save_json(CONFIG_FILE, self.config, indent=2)
        except OSError:
            pass

    def set_error(self, msg):
        with self.lock:
            self.error, self.error_at = msg, time.time()
        self.changed()

    def station(self):
        return self.catalog.get(self.station_id) if self.station_id else None

    def stream_url(self, st):
        return st["urlLow"] if self.config["quality"] == "low" else st["url"]

    # -- mpv lifecycle --

    def adopt(self):
        """Reconnect to an mpv we started before a shell reload."""
        if not os.path.exists(MPV_SOCK):
            return False
        try:
            self.attach()
        except OSError:
            try:
                os.remove(MPV_SOCK)
            except OSError:
                pass
            return False
        items = self.mpv.get("playlist", []) or []
        queue = []
        for it in items:
            st = self.catalog.by_url(it.get("filename", ""))
            queue.append(st["id"] if st else "")
        with self.lock:
            self.queue = queue
            pos = self.mpv_props.get("playlist-pos", -1)
            if pos is not None and 0 <= pos < len(queue):
                self.station_id = queue[pos]
        self.on_station(adopted=True)
        return True

    def attach(self):
        m = Mpv(MPV_SOCK, self.on_mpv_event, self.on_mpv_close)
        with self.lock:
            self.mpv = m
            self.mpv_props = {}
        for i, p in enumerate(OBSERVED, 1):
            m.command("observe_property", i, p)
        for p in OBSERVED:
            self.mpv_props[p] = m.get(p)
        self.changed()

    def launch(self, playlist):
        if not shutil.which("mpv"):
            raise OSError("mpv isn't installed; install the mpv package")
        try:
            os.remove(MPV_SOCK)
        except OSError:
            pass
        args = ["mpv", "--no-config", "--no-video", "--no-terminal", "--idle=no", "--force-window=no",
                "--input-ipc-server=" + MPV_SOCK, "--audio-client-name=Airwaves", "--title=Airwaves",
                "--volume=%d" % int(self.config["volume"]), "--volume-max=100",
                "--cache=yes", "--demuxer-max-bytes=8MiB", "--network-timeout=20",
                "--loop-file=inf", "--loop-playlist=inf", "--ytdl=no", "--user-agent=" + UA,
                "--af=@viz:lavfi=[asetnsamples=n=1024,astats=metadata=1:reset=1:measure_perchannel=none:measure_overall=RMS_level+Peak_level]"]
        script = mpris_script()
        if script:
            args.append("--script=" + script)
        args.append(playlist)
        subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        for _ in range(60):
            time.sleep(0.1)
            if os.path.exists(MPV_SOCK):
                try:
                    self.attach()
                    return
                except OSError:
                    continue
        raise OSError("mpv didn't start")

    def on_mpv_close(self, m):
        with self.lock:
            if self.mpv is not m:
                return
            self.mpv = None
            self.mpv_props = {}
            self.track = None
            self.extra = {}
        self.set_mpris_title("")
        self.changed()

    def on_mpv_event(self, msg):
        ev = msg.get("event")
        if ev == "property-change":
            name, data = msg.get("name"), msg.get("data")
            with self.lock:
                old = self.mpv_props.get(name)
                self.mpv_props[name] = data
            if name == "playlist-pos" and data is not None and data >= 0 and data != old:
                with self.lock:
                    sid = self.queue[data] if data < len(self.queue) else ""
                if sid and self.switch_station(sid):
                    self.save_config()
                    self.on_station()
            elif name == "metadata":
                self.on_icy()
            elif name == "volume" and data is not None and not self.fading:
                v = int(round(data))
                if v != self.config["volume"]:
                    self.config["volume"] = v
                    self.save_config()
            self.changed()
        elif ev == "end-file" and msg.get("reason") == "error":
            st = self.station()
            self.failures += 1
            self.set_error("Couldn't reach %s" % (st["name"] if st else "the stream"))
            if self.failures >= max(3, min(len(self.queue), 6)):
                self.stop(user=False)
                self.set_error("Couldn't reach any station; check your connection")
        elif ev == "file-loaded":
            self.failures = 0

    def cmd(self, *args):
        m = self.mpv
        if not m:
            raise OSError("not playing")
        return m.command(*args)

    def set_mpris_title(self, text):
        m = self.mpv
        if m:
            try:
                m.set("force-media-title", text)
            except OSError:
                pass

    # -- playback --

    def switch_station(self, sid):
        """Point at a new station and drop the old song in one step."""
        with self.lock:
            if sid == self.station_id and self.track is not None:
                return False
            self.station_id = sid
            self.config["last"] = sid
            self.track = None
            self.extra = {}
        self.changed()
        return True

    def queue_for(self, sid):
        favs = [f for f in self.config["favorites"] if self.catalog.get(f)]
        if sid in favs:
            return favs
        st = self.catalog.get(sid)
        return self.catalog.ids(st["net"])

    def write_queue(self, ids):
        lines = ["#EXTM3U"]
        for i in ids:
            st = self.catalog.get(i)
            lines.append("#EXTINF:-1,%s" % st["name"].replace("\n", " "))
            lines.append(self.stream_url(st))
        with open(QUEUE_FILE, "w") as f:
            f.write("\n".join(lines) + "\n")

    def play(self, sid=None):
        if not sid:
            m = self.mpv
            if m and self.mpv_props.get("pause"):
                return self.resume()
            if m:
                return True
            sid = self.config.get("last") or (self.config["favorites"] or self.catalog.ids())[0]
        st = self.catalog.get(sid)
        if not st:
            raise ValueError("unknown station")
        with self.lock:
            same = self.mpv and sid in self.queue and sorted(self.queue) == sorted(self.queue_for(sid))
        switched = self.switch_station(sid)
        if same:
            self.cmd("playlist-play-index", self.queue.index(sid))
            self.cmd("set_property", "pause", False)
        else:
            q = self.queue_for(sid)
            i = q.index(sid)
            q = q[i:] + q[:i]
            with self.lock:
                self.queue = q
            self.write_queue(q)
            if self.mpv:
                self.cmd("loadlist", QUEUE_FILE, "replace")
                self.cmd("set_property", "pause", False)
            else:
                self.launch(QUEUE_FILE)
        with self.lock:
            self.config["wasPlaying"] = True
            self.error = ""
        self.save_config()
        if switched:
            self.on_station()
        return True

    def resume(self):
        if not self.mpv:
            return self.play()
        stale = self.paused_at and time.time() - self.paused_at > 20
        self.paused_at = 0
        if stale:
            # Live radio: jump back to now instead of playing what was buffered.
            pos = self.mpv_props.get("playlist-pos") or 0
            self.cmd("playlist-play-index", pos)
        self.cmd("set_property", "pause", False)
        self.config["wasPlaying"] = True
        self.save_config()
        return True

    def pause(self):
        self.cmd("set_property", "pause", True)
        self.paused_at = time.time()
        self.config["wasPlaying"] = False
        self.save_config()
        return True

    def toggle(self):
        if not self.mpv:
            return self.play()
        return self.resume() if self.mpv_props.get("pause") else self.pause()

    def stop(self, user=True):
        m = self.mpv
        self.sleep_at = 0
        self.config["sleepAt"] = 0
        if m:
            try:
                m.command("quit")
            except OSError:
                pass
        if user:
            self.config["wasPlaying"] = False
            self.save_config()
        self.changed()
        return True

    def step(self, d):
        if not self.mpv:
            ids = self.queue_for(self.config.get("last") or self.catalog.ids()[0])
            cur = self.config.get("last")
            i = ids.index(cur) if cur in ids else -d
            return self.play(ids[(i + d) % len(ids)])
        self.cmd("playlist-next" if d > 0 else "playlist-prev", "force")
        self.cmd("set_property", "pause", False)
        return True

    def volume(self, value=None, delta=None):
        v = int(self.config["volume"])
        v = max(0, min(100, int(value) if value is not None else v + int(delta or 0)))
        self.config["volume"] = v
        self.save_config()
        if self.mpv:
            self.cmd("set_property", "volume", v)
            if v > 0 and self.mpv_props.get("mute"):
                self.cmd("set_property", "mute", False)
        self.changed()
        return True

    def mute(self):
        self.cmd("cycle", "mute")
        return True

    def favorite(self, sid, on):
        if not self.catalog.get(sid):
            raise ValueError("unknown station")
        favs = [f for f in self.config["favorites"] if f != sid]
        if on:
            favs.append(sid)
        self.config["favorites"] = favs
        self.save_config()
        self.changed()
        return True

    def move_favorite(self, sid, d):
        favs = list(self.config["favorites"])
        if sid not in favs:
            return False
        i = favs.index(sid)
        j = max(0, min(len(favs) - 1, i + d))
        favs.insert(j, favs.pop(i))
        self.config["favorites"] = favs
        self.save_config()
        self.changed()
        return True

    def sleep(self, minutes):
        m = float(minutes or 0)
        self.sleep_at = time.time() + m * 60 if m > 0 else 0
        self.config["sleepAt"] = self.sleep_at
        self.save_config()
        self.changed()
        return True

    def tick_sleep(self):
        if not self.sleep_at or not self.mpv:
            if self.fading:
                self.fading = False
            return
        left = self.sleep_at - time.time()
        if left <= 0:
            self.stop(user=True)
            self.fading = False
            return
        if left < 30:
            # Fade out over the last 30 s; config volume stays as it was.
            self.fading = True
            try:
                self.cmd("set_property", "volume", int(self.config["volume"] * left / 30))
            except OSError:
                pass

    # -- songs --

    def current(self):
        """The current track as a plain dict, with album art merged in."""
        with self.lock:
            t = dict(self.track) if self.track else None
            if t and self.extra.get("key") == t.get("key"):
                for k in ("art", "album", "year"):
                    if self.extra.get(k) and not t.get(k):
                        t[k] = self.extra[k]
            return t

    def on_station(self, adopted=False):
        """New station: let its source fill in the song. mpv's metadata still
        belongs to the previous stream until the new one loads, so ICY titles
        are only read here when adopting an mpv that's already playing."""
        st = self.station()
        if not st:
            return
        if st["icy"]:
            self.set_mpris_title("")
            if adopted:
                self.on_icy()
        elif st["now"]:
            self.set_track(dict(st["now"]))
        else:
            self.set_mpris_title(st["name"])
        self.due["current"] = 0
        self.changed()

    def on_icy(self):
        st = self.station()
        if not st or not st["icy"]:
            return
        meta = self.mpv_props.get("metadata") or {}
        raw = meta.get("icy-title") or meta.get("title") or ""
        artist, title = split_icy(raw)
        if not title:
            return
        if st["net"] in ("soma", "rp") and STATION_ID.search(artist + " " + title):
            return  # station IDs between songs
        self.set_track({"artist": artist, "title": title})
        if st["net"] == "rp":
            self.due["current"] = 0  # fetch the cover

    def set_track(self, t):
        st = self.station()
        if not st:
            return
        t["key"] = track_key(t.get("artist", ""), t.get("title", ""))
        with self.lock:
            same = self.track and self.track.get("key") == t["key"]
            if same:
                merged = dict(self.track)
                merged.update({k: v for k, v in t.items() if v})
                self.track = merged
            else:
                t["since"] = time.time()
                t["station"] = st["id"]
                self.track = t
                self.extra = {}
        if not st["icy"]:
            if t.get("show"):
                self.set_mpris_title("%s · %s" % (st["name"], t.get("title")) if t.get("title") else st["name"])
            else:
                self.set_mpris_title(" – ".join(x for x in (t.get("artist"), t.get("title")) if x) or st["name"])
        if not same:
            if not t.get("show") and t.get("title"):
                self.add_history(t, st)
            # Paradise and FIP send their own covers; look up everyone else's.
            if not t.get("art") and t.get("artist") and self.config["lookupArt"] and st["net"] not in ("rp", "fip"):
                self.pool.submit(self.find_art, t["key"], t["artist"], t["title"])
            if self.config["notify"]:
                self.notify_track()
        self.changed()

    def find_art(self, key, artist, title):
        res = self.lookup.find(artist, title)
        if not res:
            return
        with self.lock:
            if self.track and self.track.get("key") == key and not (self.extra.get("key") == key and self.extra.get("art")):
                self.extra = dict(res, key=key)
        self.fill_history(key, res)
        self.changed()

    def fill_history(self, key, info):
        """Give a history entry the cover and album found after it was added."""
        changed = False
        with self.lock:
            for h in self.history:
                if h.get("key") == key and not h.get("art") and info.get("art"):
                    h["art"] = info["art"]
                    h["album"] = h.get("album") or info.get("album", "")
                    changed = True
        if changed:
            try:
                save_json(HISTORY_FILE, self.history)
            except OSError:
                pass

    def add_history(self, t, st):
        entry = {"key": t["key"], "artist": t.get("artist", ""), "title": t.get("title", ""),
                 "album": t.get("album", ""), "art": t.get("art", ""), "station": st["id"],
                 "stationName": st["name"], "net": st["net"], "ts": int(time.time())}
        with self.lock:
            if self.history and self.history[0].get("key") == entry["key"]:
                return
            self.history.insert(0, entry)
            del self.history[60:]
        try:
            save_json(HISTORY_FILE, self.history)
        except OSError:
            pass

    def like(self, key=None):
        if key:
            src = next((h for h in self.history if h.get("key") == key), None)
            t = dict(src) if src else None
        else:
            t = self.current()
            st = self.station()
            if t and st:
                t.update({"station": st["id"], "stationName": st["name"], "net": st["net"]})
        if not t or not t.get("title"):
            raise ValueError("nothing to like right now")
        with self.lock:
            if any(l.get("key") == t["key"] for l in self.liked):
                self.liked = [l for l in self.liked if l.get("key") != t["key"]]
                liked = False
            else:
                self.liked.insert(0, {"key": t["key"], "artist": t.get("artist", ""), "title": t.get("title", ""),
                                      "album": t.get("album", ""), "year": t.get("year", ""), "art": t.get("art", ""),
                                      "show": bool(t.get("show")), "station": t.get("station", ""),
                                      "stationName": t.get("stationName", ""), "net": t.get("net", ""),
                                      "ts": int(time.time())})
                liked = True
        save_json(LIKED_FILE, self.liked, indent=1)
        self.changed()
        return liked

    def unlike(self, key):
        with self.lock:
            self.liked = [l for l in self.liked if l.get("key") != key]
        save_json(LIKED_FILE, self.liked, indent=1)
        self.changed()
        return True

    def find_song(self, key=None):
        if key:
            t = next((x for x in self.liked + self.history if x.get("key") == key), None)
        else:
            t = self.current()
        if not t or not t.get("title"):
            raise ValueError("no song to look up")
        return t

    # -- notifications --

    def notify(self, tag, summary, body, icon="", actions=(), slot=None):
        self.notifier.send(tag, summary, body, icon, actions, slot)

    def on_notification_action(self, tag, action):
        if tag.startswith("track:") and action == "like":
            key = tag[6:]
            if not any(l.get("key") == key for l in self.liked):
                try:
                    self.like(key)
                except ValueError:
                    pass

    def notify_track(self):
        t, st = self.current(), self.station()
        if t and st:
            self.notify("track:" + t["key"], t.get("title") or st["name"],
                        " · ".join(x for x in (t.get("artist"), st["name"]) if x), self.art.get(t.get("art", "")),
                        ["like", "♥ Like"] if t.get("title") and not t.get("show") else [], slot="track")

    # -- custom stations --

    def add_custom(self, name, url):
        url = (url or "").strip()
        if not url.startswith(("http://", "https://")):
            raise ValueError("stream URL must start with http:// or https://")
        entries = load_json(CUSTOM_FILE, [])
        entries = entries if isinstance(entries, list) else entries.get("stations", [])
        entries.append({"name": (name or "").strip() or url, "url": url})
        self.catalog.save_custom(entries)
        self.catalog.build()
        self.changed()
        return True

    def remove_custom(self, sid):
        st = self.catalog.get(sid)
        if not st or st["net"] != "custom":
            raise ValueError("not one of your stations")
        entries = load_json(CUSTOM_FILE, [])
        entries = [e for e in (entries if isinstance(entries, list) else entries.get("stations", []))
                   if e.get("url") != st["url"]]
        self.catalog.save_custom(entries)
        self.catalog.build()
        self.config["favorites"] = [f for f in self.config["favorites"] if f != sid]
        self.save_config()
        self.changed()
        return True

    # -- background fetching --

    def schedule(self):
        """(job, interval seconds) for everything worth fetching right now."""
        st = self.station()
        playing = bool(self.mpv) and st is not None
        jobs = [("soma", 60 if self.panel_open else 600), ("rp-list", 300 if self.panel_open else 1800),
                ("nts-mix", 6 * 3600)]
        if self.panel_open:
            jobs += [("rp-now", 45), ("fip-now", 45)]
        if self.panel_open or (playing and st["net"] == "nts"):
            jobs.append(("nts-live", 90))
        if playing and st["net"] in ("fip", "rp"):
            jobs.append(("current", 15))
        if self.catalog.custom_changed():
            jobs.append(("custom", 0))
        return jobs

    def run_job(self, job):
        try:
            if job == "soma":
                self.catalog.fetch_soma()
            elif job == "rp-list":
                self.catalog.fetch_rp_listeners()
            elif job == "rp-now":
                self.catalog.fetch_rp_now()
            elif job == "fip-now":
                self.catalog.fetch_fip_now()
            elif job == "nts-live":
                self.catalog.fetch_nts_live()
                st = self.station()
                if st and st.get("nts") and st["now"]:
                    self.set_track(dict(st["now"]))
            elif job == "nts-mix":
                self.catalog.fetch_nts_mixtapes()
            elif job == "custom":
                self.catalog.build()
            elif job == "current":
                self.refresh_current()
        except Exception as exc:
            self.emit({"type": "log", "error": "%s: %r" % (job, exc)})
            self.due[job] = time.time() + 60  # back off
        finally:
            with self.lock:
                self.busy.discard(job)
                self.last_run[job] = time.time()
            self.changed()

    def refresh_current(self):
        st = self.station()
        if not st:
            return
        if st.get("fip"):
            now = self.catalog.fip_now(st["fip"])
            if now:
                with self.catalog.lock:
                    st["now"] = now
                self.set_track(dict(now))
        elif "rp" in st:
            now = self.catalog.rp_now(st["rp"])
            with self.catalog.lock:
                st["now"] = now
            t = self.current()
            # The API runs a little ahead of the stream; only take the cover
            # when it's the song we're actually hearing.
            if t and track_key(now["artist"], now["title"]) == t["key"]:
                with self.lock:
                    self.extra = {"key": t["key"], "art": now["art"], "album": now["album"], "year": now["year"]}
                self.fill_history(t["key"], now)

    def fetch_due(self):
        now = time.time()
        for job, every in self.schedule():
            with self.lock:
                if job in self.busy or now < self.due.get(job, 0):
                    continue
                self.busy.add(job)
                self.due[job] = now + every
            self.pool.submit(self.run_job, job)

    # -- state --

    def status(self):
        p = self.mpv_props
        if not self.mpv:
            return "stopped"
        if p.get("pause"):
            return "paused"
        if p.get("paused-for-cache") or p.get("core-idle"):
            return "buffering"
        return "playing"

    def station_view(self, st):
        v = {k: st[k] for k in ("id", "net", "name", "genre", "desc", "listeners")}
        v["logo"] = self.art.get(st["art"])
        now = st.get("now")
        if now:
            v["now"] = {k: now.get(k) for k in ("artist", "title", "show", "next") if now.get(k)}
        return v

    def snapshot(self):
        with self.lock:
            if self.error and time.time() - self.error_at > 12:
                self.error = ""
            st = self.station()
            t = self.current()
            if t:
                t["artLocal"] = self.art.get(t.get("art", ""))
                t["liked"] = any(l.get("key") == t["key"] for l in self.liked)
            liked_keys = {l.get("key") for l in self.liked}
            history = []
            for h in self.history[:40]:
                h2 = dict(h, artLocal=self.art.get(h.get("art", "")), liked=h.get("key") in liked_keys)
                history.append(h2)
            liked = [dict(l, artLocal=self.art.get(l.get("art", ""))) for l in self.liked]
            with self.catalog.lock:
                stations = [self.station_view(self.catalog.stations[i]) for i in self.catalog.order]
            nets = [dict(n, count=sum(1 for s in stations if s["net"] == n["id"])) for n in NETWORKS]
            p = self.mpv_props
            return {
                "status": self.status(),
                "error": self.error,
                "station": self.station_view(st) if st and self.mpv else None,
                "lastStation": self.config.get("last", ""),
                "track": t if self.mpv else None,
                "volume": int(self.config["volume"]),
                "muted": bool(p.get("mute")),
                "bitrate": int((p.get("audio-bitrate") or 0) / 1000),
                "codec": p.get("audio-codec-name") or "",
                "queue": list(self.queue) if self.mpv else [],
                "favorites": [f for f in self.config["favorites"] if self.catalog.get(f)],
                "sleepAt": int(self.sleep_at),
                "config": {k: v for k, v in self.config.items() if k not in ("favorites", "last", "wasPlaying", "sleepAt")},
                "networks": [n for n in nets if n["count"] or n["id"] != "custom"],
                "stations": stations,
                "liked": liked,
                "history": history,
                "mpv": bool(shutil.which("mpv")),
                "mpris": bool(mpris_script()),
                "customFile": CUSTOM_FILE,
            }

    def summary(self):
        st, t = self.station(), self.current()
        return {"status": self.status(), "station": st["name"] if st and self.mpv else "",
                "artist": (t or {}).get("artist", ""), "title": (t or {}).get("title", ""),
                "volume": self.config["volume"], "sleepAt": int(self.sleep_at)}

    # -- levels for the visualizer --

    def level_loop(self):
        period = 1.0 / LEVEL_HZ
        quiet = 0
        while True:
            time.sleep(period)
            m = self.mpv
            if not m or not self.config["visualizer"] and not self.panel_open or self.status() != "playing":
                if quiet == 0:
                    self.emit({"type": "level", "r": 0, "p": 0})
                quiet = 1
                time.sleep(0.25)
                continue
            quiet = 0
            try:
                meta = m.command("get_property", "af-metadata/viz", timeout=1) or {}
                rms = float(meta.get("lavfi.astats.Overall.RMS_level", "-90"))
                peak = float(meta.get("lavfi.astats.Overall.Peak_level", "-90"))
            except (OSError, ValueError, TypeError):
                continue
            # -50 dB .. -6 dB  ->  0 .. 1
            r = max(0.0, min(1.0, (rms + 50) / 44)) if rms > -200 else 0
            pk = max(0.0, min(1.0, (peak + 40) / 40)) if peak > -200 else 0
            self.emit({"type": "level", "r": round(r, 3), "p": round(pk, 3)})

    # -- commands --

    def handle(self, msg):
        cmd = msg.get("cmd")
        if cmd == "play":
            if msg.get("query"):
                sid = self.catalog.find(str(msg["query"]))
                if not sid:
                    raise ValueError("no station matches %r" % msg["query"])
                return self.play(sid)
            return self.play(msg.get("station") or None)
        if cmd == "toggle":
            return self.toggle()
        if cmd == "pause":
            return self.pause() if self.mpv else True
        if cmd == "resume":
            return self.resume()
        if cmd == "stop":
            return self.stop()
        if cmd == "next":
            return self.step(1)
        if cmd == "prev":
            return self.step(-1)
        if cmd == "volume":
            return self.volume(msg.get("value"), msg.get("delta"))
        if cmd == "mute":
            return self.mute()
        if cmd == "favorite":
            return self.favorite(str(msg.get("station")), bool(msg.get("on", True)))
        if cmd == "moveFavorite":
            return self.move_favorite(str(msg.get("station")), int(msg.get("delta") or 0))
        if cmd == "like":
            liked = self.like(msg.get("key"))
            if msg.get("announce"):
                t = self.find_song(msg.get("key")) if msg.get("key") else self.current()
                self.notify("like", ("♥ Liked" if liked else "Removed from liked"),
                            " – ".join(x for x in (t.get("artist"), t.get("title")) if x),
                            self.art.get(t.get("art", "")))
            return liked
        if cmd == "unlike":
            return self.unlike(str(msg.get("key")))
        if cmd == "sleep":
            return self.sleep(msg.get("minutes"))
        if cmd == "search":
            t = self.find_song(msg.get("key"))
            return open_url(search_url(msg.get("service") or self.config["search"], t.get("artist", ""), t.get("title", "")))
        if cmd == "copy":
            t = self.find_song(msg.get("key"))
            return copy_text(" – ".join(x for x in (t.get("artist"), t.get("title")) if x))
        if cmd == "open":
            return open_url(str(msg.get("url") or ""))
        if cmd == "config":
            for k, v in msg.items():
                if k in DEFAULT_CONFIG and k not in ("favorites", "last", "wasPlaying", "volume", "sleepAt"):
                    self.config[k] = type(DEFAULT_CONFIG[k])(v)
            self.save_config()
            if "quality" in msg and self.mpv and self.station_id:
                sid = self.station_id
                with self.lock:
                    self.queue = []
                self.play(sid)
            self.changed()
            return True
        if cmd == "panel":
            self.panel_open = bool(msg.get("open"))
            if self.panel_open:
                for j in ("rp-now", "fip-now", "nts-live", "soma"):
                    if time.time() - self.last_run.get(j, 0) > 20:
                        self.due[j] = 0
            self.changed()
            return True
        if cmd == "addStation":
            return self.add_custom(msg.get("name"), msg.get("url"))
        if cmd == "removeStation":
            return self.remove_custom(str(msg.get("station")))
        if cmd == "refresh":
            self.due.clear()
            self.changed()
            return True
        if cmd == "status":
            return self.summary()
        if cmd == "stations":
            return [{"id": s["id"], "name": s["name"], "net": s["net"], "genre": s["genre"]}
                    for s in self.snapshot()["stations"]]
        raise ValueError("unknown command %r" % cmd)


# ---------------------------------------------------------------- daemon

def serve_control(engine, emit):
    try:
        os.remove(CTL_SOCK)
    except OSError:
        pass
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(CTL_SOCK)
    os.chmod(CTL_SOCK, 0o600)
    srv.listen(8)

    def client(conn):
        with conn:
            try:
                conn.settimeout(15)
                line = conn.makefile("r").readline()
                msg = json.loads(line)
                try:
                    data = engine.handle(msg)
                    reply = {"ok": True, "data": data, "summary": engine.summary()}
                except (ValueError, OSError) as exc:
                    reply = {"ok": False, "error": str(exc)}
                conn.sendall((json.dumps(reply) + "\n").encode())
            except (OSError, ValueError):
                pass

    while True:
        try:
            conn, _ = srv.accept()
        except OSError:
            time.sleep(1)
            continue
        threading.Thread(target=client, args=(conn,), daemon=True).start()


def daemon():
    lock = threading.Lock()

    def emit(obj):
        with lock:
            try:
                sys.stdout.write(json.dumps(obj, separators=(",", ":"), ensure_ascii=False) + "\n")
                sys.stdout.flush()
            except BrokenPipeError:
                os._exit(0)

    engine = Engine(emit)
    threading.Thread(target=serve_control, args=(engine, emit), daemon=True).start()
    threading.Thread(target=engine.level_loop, daemon=True).start()

    def startup():
        if not engine.adopt() and engine.config["resume"] and engine.config["wasPlaying"] and engine.config["last"]:
            time.sleep(4)  # let the network come up after login
            try:
                engine.play(engine.config["last"])
            except Exception as exc:
                engine.set_error("Couldn't resume: %s" % exc)

    threading.Thread(target=startup, daemon=True).start()

    def loop():
        last = None
        while True:
            try:
                engine.fetch_due()
                engine.tick_sleep()
                blob = json.dumps(engine.snapshot(), sort_keys=True, ensure_ascii=False)
                if blob != last:
                    last = blob
                    with lock:
                        try:
                            sys.stdout.write('{"type":"state","state":' + blob + "}\n")
                            sys.stdout.flush()
                        except BrokenPipeError:
                            os._exit(0)
            except Exception as exc:
                emit({"type": "log", "error": "update failed: %r" % exc})
            if engine.wake.wait(TICK):
                time.sleep(0.15)  # coalesce bursts (logo downloads, mpv events)
            engine.wake.clear()

    threading.Thread(target=loop, daemon=True).start()

    for line in sys.stdin:
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        ok, err, data = True, None, None
        try:
            data = engine.handle(msg)
        except (ValueError, OSError) as exc:
            ok, err = False, str(exc)
        engine.changed()
        emit({"type": "result", "id": msg.get("id"), "cmd": msg.get("cmd"), "ok": ok, "error": err})
    # The shell went away. mpv keeps playing on purpose; the next daemon adopts it.


# ---------------------------------------------------------------- CLI

def ctl(msg):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(20)
    try:
        s.connect(CTL_SOCK)
    except OSError:
        sys.stderr.write("Airwaves isn't running. Enable the grivera.airwaves plugin in the Omarchy shell.\n")
        sys.exit(1)
    with s:
        s.sendall((json.dumps(msg) + "\n").encode())
        reply = json.loads(s.makefile("r").readline() or "{}")
    if not reply.get("ok"):
        sys.stderr.write("airwaves: %s\n" % reply.get("error", "no reply"))
        sys.exit(1)
    return reply


def describe(s):
    if s["status"] == "stopped":
        return "Off"
    song = " – ".join(x for x in (s["artist"], s["title"]) if x)
    out = "%s%s" % (s["station"], ("  ·  " + song) if song else "")
    if s["status"] != "playing":
        out += "  (%s)" % s["status"]
    if s.get("sleepAt"):
        out += "  · sleep in %d min" % max(1, round((s["sleepAt"] - time.time()) / 60))
    return out


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "status"
    rest = argv[2:]
    if cmd == "daemon":
        daemon()
        return 0
    if cmd == "status":
        r = ctl({"cmd": "status"})
        print(json.dumps(r["summary"], indent=2) if "--json" in rest else describe(r["summary"]))
    elif cmd in ("toggle", "stop", "next", "prev", "pause", "resume", "mute"):
        r = ctl({"cmd": cmd})
        print(describe(r["summary"]))
    elif cmd == "play":
        r = ctl({"cmd": "play", "query": " ".join(rest)} if rest else {"cmd": "play"})
        print(describe(r["summary"]))
    elif cmd == "like":
        r = ctl({"cmd": "like", "announce": True})
        print(("♥ Liked: " if r["data"] else "Unliked: ") + describe(r["summary"]))
    elif cmd in ("volume", "vol"):
        if not rest:
            print(ctl({"cmd": "status"})["summary"]["volume"])
        else:
            v = rest[0]
            r = ctl({"cmd": "volume", "delta": int(v)} if v[0] in "+-" else {"cmd": "volume", "value": int(v)})
            print(r["summary"]["volume"])
    elif cmd == "sleep":
        mins = 0 if not rest or rest[0] in ("off", "0") else float(rest[0])
        ctl({"cmd": "sleep", "minutes": mins})
        print("Sleep timer off" if not mins else "Stopping in %g min" % mins)
    elif cmd == "stations":
        for s in ctl({"cmd": "stations"})["data"]:
            print("%-26s %-8s %s" % (s["id"], NET_BY_ID[s["net"]]["short"], s["name"]))
    else:
        print(__doc__.strip())
        return 0 if cmd in ("-h", "--help", "help") else 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv) or 0)
