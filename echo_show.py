
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
echo_show.py
============
A portable "Echo Show / Alexa"-style smart-display app for laptops.

Note: the on-screen UI and the assistant's voice are in German by design
(this is a German-speaking Alexa clone). The documentation, configuration
and code structure are in English.

- Real weather via Open-Meteo (free, no API key, standard library only)
- Real Spotify control via the Spotify Web API (optional, needs Premium + a dev app)
- Automatically falls back to local MP3s / simulation if something is missing
- Does not crash when optional libraries are absent

Run:  python3 echo_show.py
Keys: see the help overlay (press ? ) or the code below.

License: MIT
"""

# ----------------------------------------------------------------------------
# KONFIGURATION  (hier anpassen)
# ----------------------------------------------------------------------------
CONFIG = {
    # Wetter-Standort automatisch bestimmen (passt sich an, wo du gerade bist)
    "weather_auto_location": True,
    # Praeziser Standort via macOS CoreLocation ("GPS", WLAN-basiert, viel genauer
    # als IP). Faellt automatisch auf IP zurueck, wenn nicht verfuegbar/erlaubt.
    # Optional zuverlaessiger: `brew install corelocationcli`
    "weather_use_gps": True,
    # Fallback-Ort, falls Auto-Standort fehlschlaegt oder auto = False
    "weather_city": "Dingolfing",

    # --- Spotify (optional). Leave empty = Spotify off, local music / simulation is used ---
    # 1. https://developer.spotify.com/dashboard  -> create an app
    # 2. Add this exact Redirect URI there: http://127.0.0.1:8888/callback
    # 3. Provide credentials via environment variables (recommended):
    #       export SPOTIFY_CLIENT_ID=...
    #       export SPOTIFY_CLIENT_SECRET=...
    #    or copy .env.example to .env and fill it in.
    #    You may also paste them directly below, but DO NOT commit real values.
    #    A Premium account is required for Play/Pause/Skip.
    "spotify_client_id": "",
    "spotify_client_secret": "",
    "spotify_redirect_uri": "http://127.0.0.1:8888/callback",

    # Ordner mit eigenen Musikdateien (.mp3/.ogg/.wav) als Fallback ohne Spotify
    "music_folder": "music",

    # Startet die App direkt im Vollbild
    "start_fullscreen": True,

    # Dauerhaft auf "Alexa" hoeren (braucht SpeechRecognition + pyaudio)
    "voice_wakeword": True,

    # Standby: Nach Inaktivitaet dunkel werden.
    # "brightness" setzt auf macOS die Helligkeit auf 0, ohne den Mac zu sperren.
    # "display_sleep" nutzt pmset displaysleepnow, kann aber je nach macOS-Einstellung sperren.
    # "black" zeigt nur einen schwarzen Vollbildschirm.
    "standby_mode": "brightness",
    "turn_display_off_in_standby": False,  # alter Schalter, bleibt nur als Fallback
    "standby_after_seconds": 300,
    "wake_brightness": 0.85,

    # Stimme der Sprachausgabe (macOS-Stimmenname, z.B. "Anna", "Markus", "Petra").
    # Leer = automatisch beste deutsche Stimme. Stimmen anzeigen: say -v "?"
    "tts_voice": "Petra",

    # Mindest-Lautstaerke der Stimme (0.0 - 1.0). Der Lautstaerke-Regler steuert
    # die Stimme zwischen diesem Floor und 100%. Bei 0% bleibt die Stimme also
    # auf diesem Wert hoerbar (Musik wird dagegen normal stumm). 0.0 = aus.
    "tts_min_volume": 0.30,

    # Lokale Spracherkennung mit Whisper (offline, kein Google).
    # Leer = aus (nutzt Google online). Modelle: "small", "medium", "large-v3".
    # large-v3 = genauste, aber auf dem MacBook Air spuerbar langsamer.
    "whisper_model": "large-v3",

    # 24h Zeitformat
    "clock_24h": True,
}

# ----------------------------------------------------------------------------
# IMPORTS
# ----------------------------------------------------------------------------
import os
import sys

# Load a local .env file (simple parser, no extra dependency) so secrets can
# stay out of the source. Format: KEY=VALUE per line, # comments allowed.
def _load_dotenv():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
    except FileNotFoundError:
        pass


_load_dotenv()

# Environment variables override the (empty) defaults in CONFIG. This is the
# recommended way to provide secrets without putting them in the source.
CONFIG["spotify_client_id"] = os.environ.get(
    "SPOTIFY_CLIENT_ID", CONFIG.get("spotify_client_id", ""))
CONFIG["spotify_client_secret"] = os.environ.get(
    "SPOTIFY_CLIENT_SECRET", CONFIG.get("spotify_client_secret", ""))
CONFIG["spotify_redirect_uri"] = os.environ.get(
    "SPOTIFY_REDIRECT_URI", CONFIG.get("spotify_redirect_uri", ""))

# macOS: erster Klick auf ein gerade inaktives Fenster soll direkt als Klick
# ankommen (sonst muss man jedes Mal doppelklicken). Muss VOR pygame.init() stehen.
os.environ.setdefault("SDL_MOUSE_FOCUS_CLICKTHROUGH", "1")

import math
import time
import json
import random
import threading
import datetime as dt
import urllib.request
import urllib.parse
import webbrowser
import io
import tempfile

# Pygame ist Pflicht. Saubere Fehlermeldung wenn es fehlt.
try:
    import pygame
except ImportError:
    print("FEHLER: pygame ist nicht installiert.")
    print("Installiere es mit:  pip install pygame")
    sys.exit(1)

# Optionale Bibliotheken -> graceful fallback
try:
    import spotipy
    from spotipy.oauth2 import SpotifyOAuth
    HAVE_SPOTIPY = True
except Exception:
    HAVE_SPOTIPY = False

try:
    import pyttsx3
    HAVE_TTS = True
except Exception:
    HAVE_TTS = False

try:
    import speech_recognition as sr
    HAVE_SR = True
except Exception:
    HAVE_SR = False

try:
    from faster_whisper import WhisperModel
    import numpy as _np
    HAVE_WHISPER = True
except Exception:
    HAVE_WHISPER = False

# requests + certifi (kommen mit spotipy mit) fuer zuverlaessiges HTTPS auf macOS
try:
    import requests as _requests
    HAVE_REQUESTS = True
except Exception:
    HAVE_REQUESTS = False

import ssl as _ssl
try:
    import certifi as _certifi
    _SSL_CTX = _ssl.create_default_context(cafile=_certifi.where())
except Exception:
    try:
        _SSL_CTX = _ssl.create_default_context()
    except Exception:
        _SSL_CTX = None

import platform as _platform
import subprocess as _subprocess
import ast as _ast
import operator as _operator

APP_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(APP_DIR, "echo_show_state.json")


# ----------------------------------------------------------------------------
# THEME / FARBEN
# ----------------------------------------------------------------------------
class Theme:
    """Farbschema. Kann zwischen Tag- und Nachtmodus umschalten."""

    DAY = {
        "bg_top":      (10, 14, 28),
        "bg_bottom":   (20, 26, 50),
        "accent":      (0, 202, 255),
        "accent2":     (132, 100, 255),
        "card":        (26, 32, 54),
        "card_hover":  (38, 46, 76),
        "card_line":   (52, 62, 96),
        "text":        (236, 241, 250),
        "muted":       (150, 162, 188),
        "good":        (60, 220, 150),
        "warn":        (255, 184, 70),
        "danger":      (255, 96, 110),
    }
    NIGHT = {
        "bg_top":      (2, 4, 10),
        "bg_bottom":   (6, 9, 20),
        "accent":      (60, 120, 150),
        "accent2":     (80, 64, 130),
        "card":        (12, 16, 28),
        "card_hover":  (18, 24, 40),
        "card_line":   (26, 32, 50),
        "text":        (170, 185, 205),
        "muted":       (90, 102, 124),
        "good":        (50, 150, 110),
        "warn":        (170, 130, 60),
        "danger":      (180, 80, 90),
    }

    def __init__(self):
        self.night = False

    def __getattr__(self, name):
        # erlaubt theme.accent etc.
        data = Theme.NIGHT if self.__dict__.get("night") else Theme.DAY
        if name in data:
            return data[name]
        raise AttributeError(name)


# ----------------------------------------------------------------------------
# FONT-CACHE  + ZEICHEN-HELFER
# ----------------------------------------------------------------------------
_FONT_CACHE = {}
# Moderne, gut lesbare Schrift; faellt auf Default zurueck.
_FONT_NAMES = "helveticaneue,sfprodisplay,arial,dejavusans,sans"


def get_font(size, bold=False):
    key = (size, bold)
    if key not in _FONT_CACHE:
        try:
            f = pygame.font.SysFont(_FONT_NAMES, size, bold=bold)
        except Exception:
            f = pygame.font.Font(None, size)
        _FONT_CACHE[key] = f
    return _FONT_CACHE[key]


def draw_text(surf, text, size, color, pos, bold=False, center=False,
              right=False, alpha=255):
    font = get_font(size, bold)
    img = font.render(str(text), True, color)
    if alpha < 255:
        img.set_alpha(alpha)
    rect = img.get_rect()
    if center:
        rect.center = pos
    elif right:
        rect.midright = pos
    else:
        rect.topleft = pos
    surf.blit(img, rect)
    return rect


def fit_text(text, size, max_width, bold=False):
    """Kuerzt Text mit '...' falls er zu breit ist."""
    font = get_font(size, bold)
    if font.size(text)[0] <= max_width:
        return text
    while text and font.size(text + "...")[0] > max_width:
        text = text[:-1]
    return text + "..."


_GRADIENT_CACHE = {}


def gradient_surface(size, top, bottom):
    key = (size, top, bottom)
    s = _GRADIENT_CACHE.get(key)
    if s is not None:
        return s
    w, h = size
    s = pygame.Surface((w, h)).convert()
    for y in range(h):
        t = y / max(1, h - 1)
        col = (int(top[0] + (bottom[0] - top[0]) * t),
               int(top[1] + (bottom[1] - top[1]) * t),
               int(top[2] + (bottom[2] - top[2]) * t))
        pygame.draw.line(s, col, (0, y), (w, y))
    # cache begrenzen
    if len(_GRADIENT_CACHE) > 8:
        _GRADIENT_CACHE.clear()
    _GRADIENT_CACHE[key] = s
    return s


def lerp(a, b, t):
    return a + (b - a) * t


def ease(t):
    return t * t * (3 - 2 * t)


# ----------------------------------------------------------------------------
# WETTER-SERVICE  (echt, Open-Meteo, im Hintergrund-Thread)
# ----------------------------------------------------------------------------
WMO = {
    0: ("Klar", "sun"),
    1: ("Ueberwiegend klar", "sun"),
    2: ("Teils bewoelkt", "partly"),
    3: ("Bedeckt", "cloud"),
    45: ("Nebel", "fog"), 48: ("Reifnebel", "fog"),
    51: ("Leichter Niesel", "rain"), 53: ("Niesel", "rain"), 55: ("Starker Niesel", "rain"),
    56: ("Gefrierender Niesel", "rain"), 57: ("Gefrierender Niesel", "rain"),
    61: ("Leichter Regen", "rain"), 63: ("Regen", "rain"), 65: ("Starker Regen", "rain"),
    66: ("Gefrierender Regen", "rain"), 67: ("Gefrierender Regen", "rain"),
    71: ("Leichter Schnee", "snow"), 73: ("Schnee", "snow"), 75: ("Starker Schnee", "snow"),
    77: ("Schneegriesel", "snow"),
    80: ("Regenschauer", "rain"), 81: ("Regenschauer", "rain"), 82: ("Starke Schauer", "rain"),
    85: ("Schneeschauer", "snow"), 86: ("Schneeschauer", "snow"),
    95: ("Gewitter", "storm"), 96: ("Gewitter + Hagel", "storm"), 99: ("Gewitter + Hagel", "storm"),
}
DAYS_DE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
DAYS_DE_FULL = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


class WeatherService:
    def __init__(self, city, auto=False, use_gps=False):
        self.city = city
        self.auto = auto
        self.use_gps = use_gps
        self._gps_cache = None     # (lat, lon, name) - GPS aendert sich selten
        self.data = None          # dict mit current + forecast
        self.status = "Lade Wetter..."
        self.ok = False
        self.last_update = 0
        self._lock = threading.Lock()
        self.refresh()

    def refresh(self):
        threading.Thread(target=self._fetch, daemon=True).start()

    def _get_json(self, url, timeout=8):
        # requests (mit certifi) bevorzugen -> stabiles HTTPS auf macOS
        if HAVE_REQUESTS:
            r = _requests.get(url, headers={"User-Agent": "EchoShowNotebook/1.0"},
                              timeout=timeout)
            r.raise_for_status()
            return r.json()
        req = urllib.request.Request(url, headers={"User-Agent": "EchoShowNotebook/1.0"})
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as r:
            return json.loads(r.read().decode("utf-8"))

    def _gps_location(self):
        """Praezise Ortung via macOS CoreLocation. Liefert (lat, lon, name) oder None.
        Reihenfolge: CoreLocationCLI (falls installiert) -> pyobjc CLLocationManager."""
        if _platform.system() != "Darwin":
            return None
        coords = self._gps_corelocation_cli() or self._gps_pyobjc()
        if not coords:
            return None
        lat, lon = coords
        name = self._reverse_geocode(lat, lon) or "Mein Standort"
        return lat, lon, name

    def _gps_corelocation_cli(self):
        """`brew install corelocationcli` -> liefert lat/lon zuverlaessig auf macOS."""
        try:
            out = _subprocess.run(
                ["CoreLocationCLI", "-once", "-format", "%latitude %longitude"],
                capture_output=True, text=True, timeout=15,
            )
            parts = out.stdout.strip().split()
            if len(parts) >= 2:
                return float(parts[0]), float(parts[1])
        except Exception:
            pass
        return None

    def _gps_pyobjc(self):
        """Nativer Weg ohne Extra-Tool. Braucht pyobjc-framework-CoreLocation und
        einmalig Standort-Freigabe fuer das ausfuehrende Programm (Terminal/Python)
        unter Systemeinstellungen > Datenschutz > Ortungsdienste."""
        try:
            from CoreLocation import CLLocationManager, kCLLocationAccuracyHundredMeters
            from Foundation import NSRunLoop, NSDate
        except Exception:
            return None
        try:
            mgr = CLLocationManager.alloc().init()
            mgr.setDesiredAccuracy_(kCLLocationAccuracyHundredMeters)
            try:
                mgr.requestWhenInUseAuthorization()
            except Exception:
                pass
            mgr.startUpdatingLocation()
            deadline = time.time() + 8
            loc = None
            while time.time() < deadline:
                loc = mgr.location()
                if loc is not None:
                    break
                NSRunLoop.currentRunLoop().runUntilDate_(
                    NSDate.dateWithTimeIntervalSinceNow_(0.3))
            mgr.stopUpdatingLocation()
            if loc is not None:
                c = loc.coordinate()
                if c.latitude or c.longitude:
                    return float(c.latitude), float(c.longitude)
        except Exception:
            pass
        return None

    def _reverse_geocode(self, lat, lon):
        """Koordinaten -> Ortsname (kostenlos, kein Key). Nur fuer die Anzeige."""
        try:
            j = self._get_json(
                "https://api.bigdatacloud.net/data/reverse-geocode-client?"
                f"latitude={lat}&longitude={lon}&localityLanguage=de", timeout=6)
            return (j.get("city") or j.get("locality")
                    or j.get("principalSubdivision") or None)
        except Exception:
            return None

    def current_coords(self):
        """Aktuelle Koordinaten besorgen: GPS bevorzugt, sonst IP. (lat, lon, name) oder None."""
        if self.use_gps:
            g = self._gps_cache or self._gps_location()
            if g:
                self._gps_cache = g
                return g
        return self._ip_location()

    def _nominatim_address(self, lat, lon):
        """Koordinaten -> volle Adresse (Strasse, PLZ, Ort) via OpenStreetMap. Kein Key."""
        try:
            j = self._get_json(
                "https://nominatim.openstreetmap.org/reverse?format=jsonv2"
                f"&lat={lat}&lon={lon}&accept-language=de&zoom=18", timeout=7)
            a = j.get("address") or {}
            road = a.get("road") or a.get("pedestrian") or a.get("footway")
            num = a.get("house_number")
            plz = a.get("postcode")
            city = (a.get("city") or a.get("town") or a.get("village")
                    or a.get("municipality") or a.get("county"))
            parts = []
            if road:
                parts.append(road + (f" {num}" if num else ""))
            loc = " ".join(x for x in (plz, city) if x)
            if loc:
                parts.append(loc)
            if parts:
                return ", ".join(parts)
            return j.get("display_name")
        except Exception:
            return None

    def current_address(self):
        """Sprachfertiger Adresstext fuer 'Wo bin ich?'. Liefert String oder None."""
        loc = self.current_coords()
        if not loc:
            return None
        lat, lon, name = loc
        addr = self._nominatim_address(lat, lon)
        if addr:
            return addr
        if name:
            return name
        return f"ungefaehr {lat:.4f} Breite, {lon:.4f} Laenge"

    def _ip_location(self):
        """Standort grob ueber die IP-Adresse bestimmen. Liefert (lat, lon, city) oder None."""
        for url in ("https://ipapi.co/json/", "http://ip-api.com/json/"):
            try:
                j = self._get_json(url, timeout=6)
                lat = j.get("latitude", j.get("lat"))
                lon = j.get("longitude", j.get("lon"))
                city = j.get("city") or self.city
                if lat is not None and lon is not None:
                    return float(lat), float(lon), city
            except Exception:
                continue
        return None

    def _fetch(self):
        try:
            lat = lon = None
            name = self.city

            # 1a) Auto-Standort: zuerst praezises GPS (CoreLocation), dann IP
            if self.auto:
                loc = None
                if self.use_gps:
                    if self._gps_cache:
                        loc = self._gps_cache          # GPS nur einmal abfragen
                    else:
                        loc = self._gps_location()
                        if loc:
                            self._gps_cache = loc
                if not loc:
                    loc = self._ip_location()          # Fallback
                if loc:
                    lat, lon, name = loc

            # 1b) Fallback: Stadt -> lat/lon via Geocoding
            if lat is None:
                g_url = ("https://geocoding-api.open-meteo.com/v1/search?name="
                         + urllib.parse.quote(self.city)
                         + "&count=1&language=de&format=json")
                g = self._get_json(g_url)
                if not g.get("results"):
                    with self._lock:
                        self.status = f"Ort '{self.city}' nicht gefunden"
                        self.ok = False
                    return
                res = g["results"][0]
                lat, lon = res["latitude"], res["longitude"]
                name = res.get("name", self.city)

            # 2) Forecast
            f_url = (f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
                     "&current=temperature_2m,weather_code,wind_speed_10m,relative_humidity_2m,apparent_temperature"
                     "&hourly=temperature_2m,weather_code,precipitation_probability,precipitation,wind_speed_10m,wind_gusts_10m,cloud_cover"
                     "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,wind_speed_10m_max,wind_gusts_10m_max,sunrise,sunset,daylight_duration,sunshine_duration,uv_index_max"
                     "&timezone=auto&forecast_days=7")
            f = self._get_json(f_url)
            cur = f["current"]
            daily = f["daily"]
            forecast = []
            for i in range(len(daily["time"])):
                def dget(key, default=0):
                    vals = daily.get(key) or []
                    return vals[i] if i < len(vals) else default
                d = dt.date.fromisoformat(daily["time"][i])
                forecast.append({
                    "date": d,
                    "day": DAYS_DE[d.weekday()],
                    "day_full": DAYS_DE_FULL[d.weekday()],
                    "code": daily["weather_code"][i],
                    "tmax": round(daily["temperature_2m_max"][i]),
                    "tmin": round(daily["temperature_2m_min"][i]),
                    "precip": round((dget("precipitation_sum") or 0), 1),
                    "precip_prob": dget("precipitation_probability_max") or 0,
                    "wind": round(dget("wind_speed_10m_max") or 0),
                    "gust": round(dget("wind_gusts_10m_max") or 0),
                    "sunrise": self._parse_dt(dget("sunrise", "")),
                    "sunset": self._parse_dt(dget("sunset", "")),
                    "daylight_hours": round((dget("daylight_duration") or 0) / 3600, 1),
                    "sunshine_hours": round((dget("sunshine_duration") or 0) / 3600, 1),
                    "uv": round(dget("uv_index_max") or 0, 1),
                })
            hourly = []
            h = f.get("hourly", {})
            for i, ts in enumerate(h.get("time", [])):
                try:
                    def hget(key, default=0):
                        vals = h.get(key) or []
                        return vals[i] if i < len(vals) else default
                    when = dt.datetime.fromisoformat(ts)
                    hourly.append({
                        "time": when,
                        "temp": round(hget("temperature_2m", 0)),
                        "code": hget("weather_code", 0),
                        "precip_prob": hget("precipitation_probability", 0) or 0,
                        "precip": hget("precipitation", 0) or 0,
                        "wind": round(hget("wind_speed_10m", 0) or 0),
                        "gust": round(hget("wind_gusts_10m", 0) or 0),
                        "cloud": hget("cloud_cover", None),
                    })
                except Exception:
                    continue
            with self._lock:
                self.data = {
                    "city": name,
                    "temp": round(cur["temperature_2m"]),
                    "feels": round(cur.get("apparent_temperature", cur["temperature_2m"])),
                    "code": cur["weather_code"],
                    "wind": round(cur["wind_speed_10m"]),
                    "humidity": cur.get("relative_humidity_2m", "-"),
                    "forecast": forecast,
                    "hourly": hourly,
                }
                self.status = "OK"
                self.ok = True
                self.last_update = time.time()
        except Exception as e:
            with self._lock:
                self.status = f"Wetter-Fehler: {type(e).__name__}"
                self.ok = False

    def _parse_dt(self, value):
        try:
            return dt.datetime.fromisoformat(value) if value else None
        except Exception:
            return None

    def get(self):
        with self._lock:
            return self.data

    def maybe_refresh(self):
        # alle 15 Minuten aktualisieren
        if time.time() - self.last_update > 900:
            self.last_update = time.time()
            self.refresh()


# ----------------------------------------------------------------------------
# SPOTIFY-SERVICE  (echt, optional)  +  lokaler Musik-Fallback
# ----------------------------------------------------------------------------
class MusicService:
    """
    Versucht in dieser Reihenfolge:
      1. Spotify (wenn konfiguriert + spotipy + Premium)
      2. Lokale Musikdateien via pygame.mixer
      3. Reine Simulation (Fake-Playlist)
    """
    FAKE_SONGS = [
        ("Midnight Drive", "Neon Avenue", 214),
        ("Coastline", "The Saltwater Club", 188),
        ("Slow Sunrise", "Aurora Keys", 241),
        ("Hotel Lobby", "Marble Lounge", 199),
        ("Far From Home", "Wanderlight", 226),
    ]

    def __init__(self, config):
        self.mode = "sim"           # sim | local | spotify
        self.status = "Simulation"
        self.sp = None
        self.local_files = []
        self.local_index = 0
        self.fake_index = 0
        self.fake_start = time.time()
        self.fake_paused = False
        self.fake_paused_at = 0.0
        self.volume = 60
        self._album_cache = {}      # url -> pygame.Surface
        self._album_loading = set()
        self._init_audio()
        self._init_spotify(config)
        if self.mode == "sim":
            self._init_local(config.get("music_folder", "music"))

    # ----- init -----
    def _init_audio(self):
        try:
            pygame.mixer.init()
            self.have_mixer = True
        except Exception:
            self.have_mixer = False

    def _init_spotify(self, config):
        cid = config.get("spotify_client_id", "").strip()
        sec = config.get("spotify_client_secret", "").strip()
        if not (HAVE_SPOTIPY and cid and sec):
            return
        try:
            auth = SpotifyOAuth(
                client_id=cid,
                client_secret=sec,
                redirect_uri=config.get("spotify_redirect_uri"),
                scope="user-read-playback-state user-modify-playback-state "
                      "user-read-currently-playing streaming",
                cache_path=".spotify_cache",
                open_browser=True,
            )
            self.sp = spotipy.Spotify(auth_manager=auth, requests_timeout=8)
            # Testaufruf (loest beim ersten Mal den Browser-Login aus)
            self.sp.devices()
            self.mode = "spotify"
            self.status = "Spotify verbunden"
        except Exception as e:
            self.sp = None
            self.status = "Spotify-Login fehlgeschlagen -> Simulation"

    def _init_local(self, folder):
        exts = (".mp3", ".ogg", ".wav")
        try:
            if os.path.isdir(folder):
                files = sorted(f for f in os.listdir(folder) if f.lower().endswith(exts))
                self.local_files = [os.path.join(folder, f) for f in files]
        except Exception:
            self.local_files = []
        if self.local_files and self.have_mixer:
            self.mode = "local"
            self.status = f"Lokal: {len(self.local_files)} Songs"

    # ----- Spotify Hintergrund-Poll -----
    def poll_spotify(self):
        """Sollte in eigenem Thread laufen (siehe App)."""
        if self.mode != "spotify" or not self.sp:
            return None
        try:
            pb = self.sp.current_playback()
            return pb
        except Exception:
            return None

    # ----- Steuerung -----
    def toggle_play(self):
        if self.mode == "spotify" and self.sp:
            try:
                pb = self.sp.current_playback()
                if pb and pb.get("is_playing"):
                    self.sp.pause_playback()
                else:
                    self.sp.start_playback()
            except Exception:
                pass
        elif self.mode == "local" and self.have_mixer:
            if not pygame.mixer.music.get_busy():
                self._play_local(self.local_index)
            else:
                if self.fake_paused:
                    pygame.mixer.music.unpause(); self.fake_paused = False
                else:
                    pygame.mixer.music.pause(); self.fake_paused = True
        else:  # sim
            if self.fake_paused:
                self.fake_start = time.time() - self.fake_paused_at
                self.fake_paused = False
            else:
                self.fake_paused_at = time.time() - self.fake_start
                self.fake_paused = True

    def play(self):
        if self.is_paused() or not self.is_playing():
            self.toggle_play()

    def _active_device_id(self):
        """ID eines Spotify-Geraets (aktives bevorzugt). None wenn keins offen."""
        try:
            devs = self.sp.devices().get("devices", [])
            if not devs:
                return None
            for d in devs:
                if d.get("is_active"):
                    return d["id"]
            return devs[0]["id"]
        except Exception:
            return None

    def play_query(self, query):
        """
        Sucht einen Titel und spielt ihn ab. 'query' z.B. 'mm3 von sofaygo'.
        Liefert (ok: bool, info_text: str).
        """
        if self.mode == "spotify" and self.sp:
            try:
                # 'Titel von Interpret' -> gezielte Suche
                if " von " in query:
                    title, artist = query.split(" von ", 1)
                    q = f"track:{title.strip()} artist:{artist.strip()}"
                else:
                    q = query
                items = self.sp.search(q=q, type="track", limit=1) \
                            .get("tracks", {}).get("items", [])
                if not items:  # Fallback ohne Filter
                    items = self.sp.search(q=query.replace(" von ", " "),
                                           type="track", limit=1) \
                                .get("tracks", {}).get("items", [])
                if not items:
                    return (False, "Den Titel habe ich nicht gefunden.")
                track = items[0]
                device_id = self._active_device_id()
                if not device_id:
                    return (False, "Kein aktives Spotify-Geraet. Oeffne Spotify kurz auf einem Geraet.")
                self.sp.start_playback(device_id=device_id, uris=[track["uri"]])
                artists = ", ".join(a["name"] for a in track["artists"])
                return (True, f"{track['name']} von {artists}")
            except Exception:
                return (False, "Beim Abspielen ist ein Spotify-Fehler aufgetreten.")

        elif self.mode == "local" and self.local_files:
            words = query.replace(" von ", " ").lower().split()
            for i, path in enumerate(self.local_files):
                base = os.path.basename(path).lower()
                if all(w in base for w in words):
                    self.local_index = i
                    self._play_local(i)
                    return (True, os.path.splitext(os.path.basename(path))[0])
            return (False, "Den Titel habe ich nicht in deinen lokalen Dateien gefunden.")

        return (False, "Gezieltes Abspielen geht nur mit Spotify oder lokalen Dateien.")

    def play_artist(self, artist):
        """Spielt einen ganzen Kuenstler (beliebte Titel). Liefert (ok, info)."""
        if self.mode == "spotify" and self.sp:
            try:
                items = self.sp.search(q=f"artist:{artist}", type="artist", limit=1) \
                            .get("artists", {}).get("items", [])
                if not items:
                    items = self.sp.search(q=artist, type="artist", limit=1) \
                                .get("artists", {}).get("items", [])
                if not items:
                    return (False, f"Den Kuenstler {artist} habe ich nicht gefunden.")
                art = items[0]
                device_id = self._active_device_id()
                if not device_id:
                    return (False, "Kein aktives Spotify-Geraet. Oeffne Spotify kurz auf einem Geraet.")
                try:
                    self.sp.shuffle(True, device_id=device_id)
                except Exception:
                    pass
                self.sp.start_playback(device_id=device_id, context_uri=art["uri"])
                return (True, art["name"])
            except Exception:
                return (False, "Beim Abspielen ist ein Spotify-Fehler aufgetreten.")
        elif self.mode == "local" and self.local_files:
            aw = artist.lower().split()
            matches = [i for i, p in enumerate(self.local_files)
                       if all(w in os.path.basename(p).lower() for w in aw)]
            if matches:
                self.local_index = matches[0]
                self._play_local(matches[0])
                return (True, artist)
            return (False, f"Keine lokalen Songs von {artist} gefunden.")
        return (False, "Kuenstler-Wiedergabe geht nur mit Spotify oder lokalen Dateien.")

    def pause(self):
        if self.is_playing():
            self.toggle_play()

    def stop(self):
        if self.mode == "spotify" and self.sp:
            try: self.sp.pause_playback()
            except Exception: pass
        elif self.mode == "local" and self.have_mixer:
            pygame.mixer.music.stop()
        else:
            self.fake_paused = True
            self.fake_paused_at = 0.0
            self.fake_start = time.time()

    def next(self):
        if self.mode == "spotify" and self.sp:
            try: self.sp.next_track()
            except Exception: pass
        elif self.mode == "local":
            self.local_index = (self.local_index + 1) % max(1, len(self.local_files))
            self._play_local(self.local_index)
        else:
            self.fake_index = (self.fake_index + 1) % len(self.FAKE_SONGS)
            self.fake_start = time.time(); self.fake_paused = False

    def prev(self):
        if self.mode == "spotify" and self.sp:
            try: self.sp.previous_track()
            except Exception: pass
        elif self.mode == "local":
            self.local_index = (self.local_index - 1) % max(1, len(self.local_files))
            self._play_local(self.local_index)
        else:
            self.fake_index = (self.fake_index - 1) % len(self.FAKE_SONGS)
            self.fake_start = time.time(); self.fake_paused = False

    def set_volume(self, v):
        self.volume = max(0, min(100, int(v)))
        if self.mode == "spotify" and self.sp:
            try: self.sp.volume(self.volume)
            except Exception: pass
        elif self.have_mixer:
            try: pygame.mixer.music.set_volume(self.volume / 100.0)
            except Exception: pass

    def change_volume(self, delta):
        self.set_volume(self.volume + delta)

    def _play_local(self, idx):
        if not self.local_files or not self.have_mixer:
            return
        try:
            pygame.mixer.music.load(self.local_files[idx])
            pygame.mixer.music.set_volume(self.volume / 100.0)
            pygame.mixer.music.play()
            self.fake_paused = False
            self.fake_start = time.time()
        except Exception:
            pass

    # ----- Status fuer UI -----
    def now_playing(self, spotify_pb=None):
        """Liefert dict: title, artist, pos, dur, playing, album_url"""
        if self.mode == "spotify":
            if spotify_pb and spotify_pb.get("item"):
                item = spotify_pb["item"]
                imgs = item.get("album", {}).get("images", [])
                url = imgs[0]["url"] if imgs else None
                return {
                    "title": item.get("name", "-"),
                    "artist": ", ".join(a["name"] for a in item.get("artists", [])),
                    "pos": (spotify_pb.get("progress_ms") or 0) / 1000.0,
                    "dur": (item.get("duration_ms") or 1) / 1000.0,
                    "playing": spotify_pb.get("is_playing", False),
                    "album_url": url,
                }
            return {"title": "Nichts aktiv", "artist": "Oeffne Spotify auf einem Geraet",
                    "pos": 0, "dur": 1, "playing": False, "album_url": None}

        if self.mode == "local" and self.local_files:
            name = os.path.basename(self.local_files[self.local_index])
            name = os.path.splitext(name)[0]
            playing = self.have_mixer and pygame.mixer.music.get_busy() and not self.fake_paused
            pos = (time.time() - self.fake_start) if playing else 0
            return {"title": name, "artist": "Lokale Datei", "pos": pos, "dur": 240,
                    "playing": playing, "album_url": None}

        # Simulation
        title, artist, dur = self.FAKE_SONGS[self.fake_index]
        if self.fake_paused:
            pos = self.fake_paused_at
        else:
            pos = time.time() - self.fake_start
            if pos >= dur:
                self.next()
                pos = 0
        return {"title": title, "artist": artist, "pos": pos % dur, "dur": dur,
                "playing": not self.fake_paused, "album_url": None}

    def is_playing(self):
        return not self.fake_paused if self.mode != "spotify" else True

    def is_paused(self):
        return self.fake_paused

    # ----- Album-Cover laden (Spotify) -----
    def get_album_image(self, url, size):
        if not url:
            return None
        key = (url, size)
        if key in self._album_cache:
            return self._album_cache[key]
        if url not in self._album_loading:
            self._album_loading.add(url)
            threading.Thread(target=self._load_album, args=(url, size, key), daemon=True).start()
        return None

    def _load_album(self, url, size, key):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "EchoShow/1.0"})
            with urllib.request.urlopen(req, timeout=8) as r:
                raw = r.read()
            img = pygame.image.load(io.BytesIO(raw))
            img = pygame.transform.smoothscale(img, (size, size))
            self._album_cache[key] = img
        except Exception:
            self._album_cache[key] = None
        finally:
            self._album_loading.discard(url)


# ----------------------------------------------------------------------------
# SPRACHE (TTS) + Mikrofon (optional)
# ----------------------------------------------------------------------------
class Voice:
    # Worte, die als "Alexa" durchgehen (Google verhoert sich gern)
    WAKE_WORDS = ("alexa", "alexah", "alex", "elexa", "computer", "aleksa", "alexia")

    def __init__(self, preferred_voice="", whisper_model="", min_volume=0.30):
        self.tts = None
        self.enabled = False
        self.is_mac = (_platform.system() == "Darwin")
        self.say_voice = (preferred_voice or "").strip() or None
        self._whisper_model_name = (whisper_model or "").strip()
        self.all_voices = []
        # Floor: die Stimme faellt nie unter diesen Wert, auch bei 0% Regler.
        self.min_volume = max(0.0, min(1.0, float(min_volume)))
        self.volume = max(self.min_volume, 0.60)
        if self.is_mac:
            # macOS 'say' = zuverlaessig + schoene Systemstimmen
            self.all_voices = self._list_say_voices()
            if not self.say_voice:
                self.say_voice = self._auto_german_voice()
            self.enabled = True
        elif HAVE_TTS:
            try:
                self.tts = pyttsx3.init()
                self.tts.setProperty("rate", 175)
                self.tts.setProperty("volume", self.volume)
                self.enabled = True
            except Exception:
                self.tts = None
        self.recognizer = sr.Recognizer() if HAVE_SR else None
        self._bg_stop = None        # Stopper-Funktion fuer Hintergrund-Listening
        self.listening = False      # Wake-Word-Modus aktiv?
        self.speaking = False       # spricht gerade (verhindert Selbst-Trigger)
        self.last_error = ""
        self._say_lock = threading.Lock()
        # Lokale Spracherkennung (Whisper) optional im Hintergrund laden
        self.whisper = None
        self.whisper_model_name = (self._whisper_model_name or "")
        if HAVE_WHISPER and self.whisper_model_name:
            threading.Thread(target=self._load_whisper, daemon=True).start()

    def _load_whisper(self):
        try:
            # int8 = schnellste/leichteste Variante auf der CPU (Apple Silicon)
            self.whisper = WhisperModel(self.whisper_model_name, device="cpu",
                                        compute_type="int8")
        except Exception:
            self.whisper = None
            self.last_error = "Whisper-Modell konnte nicht geladen werden"

    def _transcribe(self, audio):
        """Wandelt SpeechRecognition-Audio in Text. Whisper falls geladen, sonst Google."""
        if self.whisper is not None and HAVE_WHISPER:
            try:
                raw = audio.get_raw_data(convert_rate=16000, convert_width=2)
                samples = _np.frombuffer(raw, _np.int16).astype(_np.float32) / 32768.0
                segments, _info = self.whisper.transcribe(
                    samples, language="de", beam_size=1, vad_filter=True)
                return " ".join(s.text for s in segments).strip()
            except Exception:
                pass
        # Fallback: Google online
        return self.recognizer.recognize_google(audio, language="de-DE")

    def _list_say_voices(self):
        """Liste (name, sprache) aller macOS-Stimmen."""
        out_voices = []
        try:
            out = _subprocess.run(["say", "-v", "?"], capture_output=True,
                                  text=True, timeout=5).stdout
            for line in out.splitlines():
                # Format: "Anna                de_DE    # ..."
                m = re.match(r"^(.+?)\s{2,}([a-z]{2}_[A-Z]{2})", line)
                if m:
                    out_voices.append((m.group(1).strip(), m.group(2)))
        except Exception:
            pass
        return out_voices

    def _auto_german_voice(self):
        """Beste deutsche Stimme automatisch waehlen (Premium/Enhanced bevorzugt)."""
        german = [n for (n, lang) in self.all_voices if lang == "de_DE"]
        if not german:
            return None
        # Premium/Enhanced bevorzugen, sonst bekannte gute Namen, sonst erste
        for key in ("premium", "enhanced"):
            for n in german:
                if key in n.lower():
                    return n
        for pref in ("Anna", "Markus", "Petra", "Viktor"):
            if pref in german:
                return pref
        return german[0]

    # ---------- Sprachausgabe ----------
    def set_volume(self, percent):
        # Regler 0..100% linear auf [min_volume .. 1.0] abbilden.
        # -> bei 0% bleibt die Stimme auf min_volume hoerbar, bei 100% voll.
        pct = max(0.0, min(1.0, float(percent) / 100.0))
        self.volume = self.min_volume + (1.0 - self.min_volume) * pct
        if self.tts:
            try:
                self.tts.setProperty("volume", self.volume)
            except Exception:
                pass

    def say(self, text):
        if not self.enabled:
            return
        threading.Thread(target=self._say, args=(text,), daemon=True).start()

    def _say(self, text):
        with self._say_lock:
            try:
                self.speaking = True
                if self.is_mac:
                    # "12:29" -> "12 Uhr 29" fuer sauberes Vorlesen
                    spoken = re.sub(r"(\d{1,2}):(\d{2})", r"\1 Uhr \2", text)
                    tmp_path = None
                    try:
                        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".aiff")
                        tmp_path = tmp.name
                        tmp.close()
                        cmd = ["say"]
                        if self.say_voice:
                            cmd += ["-v", self.say_voice]
                        cmd += ["-o", tmp_path, spoken]
                        _subprocess.run(cmd, timeout=30)
                        _subprocess.run(["afplay", "-v", f"{self.volume:.2f}", tmp_path],
                                        timeout=30)
                    finally:
                        if tmp_path:
                            try:
                                os.unlink(tmp_path)
                            except Exception:
                                pass
                elif self.tts:
                    self.tts.say(text)
                    self.tts.runAndWait()
            except Exception:
                pass
            finally:
                self.speaking = False

    # ---------- Push-to-talk (Leertaste) ----------
    def listen_once(self, callback):
        """Hoert einmal zu und ruft callback(text) auf. Nicht blockierend."""
        if not (HAVE_SR and self.recognizer):
            callback(None)
            return
        threading.Thread(target=self._listen, args=(callback,), daemon=True).start()

    def _listen(self, callback):
        try:
            with sr.Microphone() as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=0.4)
                audio = self.recognizer.listen(source, timeout=5, phrase_time_limit=6)
            text = self._transcribe(audio)
            callback(text)
        except Exception:
            callback(None)

    # ---------- Wake-Word-Modus (dauerhaft auf "Alexa" hoeren) ----------
    def start_wakeword(self, on_command):
        """
        Hoert dauerhaft im Hintergrund. Wird ein Satz mit Wake-Word ('Alexa')
        erkannt, wird on_command(text) aufgerufen. Liefert True bei Erfolg.
        """
        if not (HAVE_SR and self.recognizer):
            self.last_error = "SpeechRecognition/pyaudio fehlt"
            return False
        if self.listening:
            return True
        try:
            mic = sr.Microphone()
            with mic as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
        except Exception as e:
            self.last_error = "Mikrofon nicht verfuegbar (Rechte?)"
            return False

        # Schnellere Reaktion: kuerzere Stille-Pause + keine staendige Re-Kalibrierung
        self.recognizer.pause_threshold = 0.5      # statt 0.8 s warten
        self.recognizer.non_speaking_duration = 0.3
        self.recognizer.dynamic_energy_threshold = False

        def _callback(recognizer, audio):
            if self.speaking:
                return  # nicht auf die eigene Stimme reagieren
            try:
                text = self._transcribe(audio)
            except Exception:
                return
            low = text.lower()
            if any(w in low for w in self.WAKE_WORDS):
                on_command(text)

        try:
            self._bg_stop = self.recognizer.listen_in_background(
                mic, _callback, phrase_time_limit=5)
            self.listening = True
            return True
        except Exception:
            self.last_error = "Hintergrund-Listening fehlgeschlagen"
            return False

    def stop_wakeword(self):
        if self._bg_stop:
            try:
                self._bg_stop(wait_for_stop=False)
            except Exception:
                pass
            self._bg_stop = None
        self.listening = False

    def toggle_wakeword(self, on_command):
        if self.listening:
            self.stop_wakeword()
            return False
        return self.start_wakeword(on_command)


# ----------------------------------------------------------------------------
# ECHTE WEBVIEW IM HAUPTFENSTER (macOS/WebKit, optional)
# ----------------------------------------------------------------------------
class EmbeddedWebView:
    """Haengt auf macOS eine echte WKWebView in das PyGame-Fenster ein."""

    def __init__(self):
        self.webview = None
        self.nswindow = None
        self.url = ""
        self.error = ""
        self._imports = None
        self._frame_key = None
        self._hidden = True

    def available(self):
        return _platform.system() == "Darwin"

    def show(self, url, rect, window_height):
        if not self.available():
            self.error = "Echtes Einbetten geht hier nur auf macOS."
            return False
        try:
            self._ensure_imports()
            created = self.webview is None
            self._ensure_webview(rect, window_height)
            frame_changed = self.set_rect(rect, window_height)
            changed_url = self.url != url
            if self.url != url:
                NSURL, NSURLRequest = self._imports["NSURL"], self._imports["NSURLRequest"]
                req = NSURLRequest.requestWithURL_(NSURL.URLWithString_(url))
                self.webview.loadRequest_(req)
                self.url = url
            was_hidden = self._hidden
            self.webview.setHidden_(False)
            self._hidden = False
            if created or changed_url or was_hidden or frame_changed:
                self.bring_to_front()
            if created or changed_url or was_hidden:
                self.focus()
            return True
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
            return False

    def set_rect(self, rect, window_height):
        if not self.webview:
            return False
        frame_key = (int(rect.x), int(rect.y), int(rect.width), int(rect.height), int(window_height))
        if frame_key == self._frame_key:
            return False
        self._frame_key = frame_key
        NSMakeRect = self._imports["NSMakeRect"]
        frame = NSMakeRect(rect.x, window_height - rect.bottom, rect.width, rect.height)
        self.webview.setFrame_(frame)
        return True

    def focus(self):
        if not self.webview:
            return
        try:
            if self.nswindow:
                self.nswindow.makeKeyAndOrderFront_(None)
                self.nswindow.makeFirstResponder_(self.webview)
        except Exception:
            pass

    def mouse_moved(self, pos, window_height):
        if not self.webview or not self.nswindow:
            return
        try:
            NSEvent = self._imports["NSEvent"]
            NSMakePoint = self._imports["NSMakePoint"]
            loc = NSMakePoint(float(pos[0]), float(window_height - pos[1]))
            event = NSEvent.mouseEventWithType_location_modifierFlags_timestamp_windowNumber_context_eventNumber_clickCount_pressure_(
                5, loc, 0, time.time(), self.nswindow.windowNumber(), None, 0, 0, 0.0
            )
            self.webview.mouseMoved_(event)
        except Exception:
            pass

    def bring_to_front(self):
        if not self.webview:
            return
        try:
            self.webview.removeFromSuperview()
            self.nswindow.contentView().addSubview_(self.webview)
        except Exception:
            pass

    def hide(self):
        if self.webview:
            try:
                self.webview.setHidden_(True)
                self._hidden = True
            except Exception:
                pass

    def close(self):
        if self.webview:
            try:
                self.webview.removeFromSuperview()
            except Exception:
                pass
        self.webview = None
        self.nswindow = None
        self.url = ""
        self._frame_key = None
        self._hidden = True

    def _ensure_imports(self):
        if self._imports is not None:
            return
        import ctypes
        import objc
        from Cocoa import NSEvent, NSMakePoint, NSMakeRect, NSURL, NSURLRequest
        from WebKit import WKWebView, WKWebViewConfiguration
        try:
            EchoWKWebView = objc.lookUpClass("EchoEmbeddedWKWebView")
        except Exception:
            try:
                class EchoEmbeddedWKWebView(WKWebView):
                    def acceptsFirstMouse_(self, event):
                        return True

                    def acceptsFirstResponder(self):
                        return True
                EchoWKWebView = EchoEmbeddedWKWebView
            except Exception:
                EchoWKWebView = WKWebView
        self._imports = {
            "ctypes": ctypes,
            "objc": objc,
            "NSEvent": NSEvent,
            "NSMakePoint": NSMakePoint,
            "NSMakeRect": NSMakeRect,
            "NSURL": NSURL,
            "NSURLRequest": NSURLRequest,
            "WKWebView": EchoWKWebView,
            "WKWebViewConfiguration": WKWebViewConfiguration,
        }

    def _ensure_webview(self, rect, window_height):
        if self.webview is not None:
            return
        info = pygame.display.get_wm_info()
        win = info.get("window")
        if win is None:
            raise RuntimeError("PyGame-Fensterhandle nicht gefunden")
        self.nswindow = self._as_nswindow(win)
        try:
            self.nswindow.setAcceptsMouseMovedEvents_(True)
        except Exception:
            pass
        content = self.nswindow.contentView()
        NSMakeRect = self._imports["NSMakeRect"]
        WKWebView = self._imports["WKWebView"]
        WKWebViewConfiguration = self._imports["WKWebViewConfiguration"]
        frame = NSMakeRect(rect.x, window_height - rect.bottom, rect.width, rect.height)
        config = WKWebViewConfiguration.alloc().init()
        self.webview = WKWebView.alloc().initWithFrame_configuration_(frame, config)
        try:
            self.webview.setAutoresizingMask_(18)  # Breite + Hoehe flexibel
        except Exception:
            pass
        content.addSubview_(self.webview)

    def _as_nswindow(self, handle):
        if hasattr(handle, "contentView"):
            return handle

        objc = self._imports["objc"]
        ctypes = self._imports["ctypes"]
        ptr = None

        if isinstance(handle, int):
            ptr = handle
        else:
            # PyGame/PySDL liefert auf manchen macOS-Versionen eine PyCapsule
            # statt eines Python-int. Daraus holen wir den nativen NSWindow*.
            get_name = ctypes.pythonapi.PyCapsule_GetName
            get_name.argtypes = [ctypes.py_object]
            get_name.restype = ctypes.c_char_p
            get_pointer = ctypes.pythonapi.PyCapsule_GetPointer
            get_pointer.argtypes = [ctypes.py_object, ctypes.c_char_p]
            get_pointer.restype = ctypes.c_void_p
            try:
                name = get_name(handle)
            except Exception:
                name = None
            try:
                ptr = get_pointer(handle, name)
            except Exception:
                ptr = None

        if not ptr:
            raise RuntimeError(f"Fensterhandle-Typ nicht unterstuetzt: {type(handle).__name__}")
        return objc.objc_object(c_void_p=ctypes.c_void_p(ptr))


# ----------------------------------------------------------------------------
# UI: BUTTON / KACHEL
# ----------------------------------------------------------------------------
APP_ICONS = {"clock", "music", "weather", "timer", "alarm",
             "browser", "notes", "random", "bello", "settings"}


def draw_app_icon(surf, name, cx, cy, s, color, theme=None):
    """Zeichnet ein sauberes Vektor-Icon. s = halbe Groesse."""
    cx, cy, s = int(cx), int(cy), int(s)
    lw = max(2, int(s * 0.12))

    def L(p1, p2, w=lw):
        pygame.draw.line(surf, color, (int(p1[0]), int(p1[1])),
                         (int(p2[0]), int(p2[1])), w)

    if name == "clock":
        pygame.draw.circle(surf, color, (cx, cy), s, lw)
        L((cx, cy), (cx, cy - s * 0.55))
        L((cx, cy), (cx + s * 0.45, cy))
    elif name == "music":
        hr = max(3, int(s * 0.30))
        hx, hy = cx - int(s * 0.1), cy + int(s * 0.45)
        pygame.draw.circle(surf, color, (hx, hy), hr)
        L((hx + hr, hy), (hx + hr, cy - s * 0.6))
        L((hx + hr, cy - s * 0.6), (hx + hr + s * 0.4, cy - s * 0.3))
    elif name == "weather":
        sun = (255, 206, 84)
        pygame.draw.circle(surf, sun, (cx - int(s * 0.25), cy - int(s * 0.2)), int(s * 0.42))
        for i in range(8):
            a = i * math.pi / 4
            x1 = cx - s * 0.25 + math.cos(a) * s * 0.5
            y1 = cy - s * 0.2 + math.sin(a) * s * 0.5
            x2 = cx - s * 0.25 + math.cos(a) * s * 0.72
            y2 = cy - s * 0.2 + math.sin(a) * s * 0.72
            L((x1, y1), (x2, y2), max(2, int(s * 0.08)))
        _cloud(surf, cx + s * 0.15, cy + s * 0.35, s * 0.55, (210, 220, 235))
    elif name == "timer":
        pygame.draw.circle(surf, color, (cx, cy + int(s * 0.12)), int(s * 0.78), lw)
        L((cx, cy - s * 0.66), (cx, cy - s * 0.95), max(2, int(s * 0.18)))
        L((cx - s * 0.22, cy - s * 0.95), (cx + s * 0.22, cy - s * 0.95), max(2, int(s * 0.18)))
        L((cx, cy + s * 0.12), (cx + s * 0.34, cy - s * 0.22))
    elif name == "alarm":
        pts = [(cx - s * 0.65, cy + s * 0.4), (cx - s * 0.5, cy - s * 0.05),
               (cx - s * 0.28, cy - s * 0.45), (cx, cy - s * 0.55),
               (cx + s * 0.28, cy - s * 0.45), (cx + s * 0.5, cy - s * 0.05),
               (cx + s * 0.65, cy + s * 0.4)]
        pygame.draw.lines(surf, color, False, [(int(a), int(b)) for a, b in pts], lw)
        L((cx - s * 0.65, cy + s * 0.4), (cx + s * 0.65, cy + s * 0.4))
        pygame.draw.circle(surf, color, (cx, cy + int(s * 0.6)), max(2, int(s * 0.16)))
        L((cx - s * 0.2, cy - s * 0.6), (cx - s * 0.45, cy - s * 0.78), max(2, int(s * 0.1)))
        L((cx + s * 0.2, cy - s * 0.6), (cx + s * 0.45, cy - s * 0.78), max(2, int(s * 0.1)))
    elif name == "browser":
        pygame.draw.circle(surf, color, (cx, cy), s, lw)
        pygame.draw.ellipse(surf, color, (cx - int(s * 0.45), cy - s,
                                          int(s * 0.9), int(s * 2)), max(2, int(lw * 0.7)))
        L((cx - s, cy), (cx + s, cy), max(2, int(lw * 0.7)))
        L((cx - s * 0.85, cy - s * 0.45), (cx + s * 0.85, cy - s * 0.45), max(2, int(lw * 0.6)))
        L((cx - s * 0.85, cy + s * 0.45), (cx + s * 0.85, cy + s * 0.45), max(2, int(lw * 0.6)))
    elif name == "notes":
        rect = pygame.Rect(int(cx - s * 0.62), int(cy - s * 0.72), int(s * 1.24), int(s * 1.44))
        pygame.draw.rect(surf, color, rect, lw, border_radius=int(s * 0.18))
        for k in range(3):
            yy = cy - s * 0.3 + k * s * 0.34
            L((cx - s * 0.35, yy), (cx + s * 0.35, yy), max(2, int(s * 0.09)))
    elif name == "random":
        pygame.draw.circle(surf, color, (cx - int(s * 0.38), cy - int(s * 0.18)), max(3, int(s * 0.18)))
        pygame.draw.circle(surf, color, (cx + int(s * 0.38), cy + int(s * 0.18)), max(3, int(s * 0.18)))
        L((cx - s * 0.2, cy - s * 0.18), (cx + s * 0.18, cy - s * 0.18), max(2, int(s * 0.08)))
        L((cx + s * 0.18, cy - s * 0.18), (cx + s * 0.06, cy - s * 0.34), max(2, int(s * 0.08)))
        L((cx + s * 0.18, cy - s * 0.18), (cx + s * 0.06, cy - s * 0.02), max(2, int(s * 0.08)))
        L((cx + s * 0.2, cy + s * 0.18), (cx - s * 0.18, cy + s * 0.18), max(2, int(s * 0.08)))
        L((cx - s * 0.18, cy + s * 0.18), (cx - s * 0.06, cy + s * 0.34), max(2, int(s * 0.08)))
        L((cx - s * 0.18, cy + s * 0.18), (cx - s * 0.06, cy + s * 0.02), max(2, int(s * 0.08)))
    elif name == "bello":
        pygame.draw.ellipse(surf, color, (int(cx - s * 0.4), int(cy + s * 0.05),
                                          int(s * 0.8), int(s * 0.7)))
        for dx, dy in ((-0.55, -0.35), (-0.18, -0.6), (0.18, -0.6), (0.55, -0.35)):
            pygame.draw.circle(surf, color, (int(cx + dx * s), int(cy + dy * s)), max(2, int(s * 0.16)))
    elif name == "settings":
        teeth = 8
        for i in range(teeth):
            a = i * 2 * math.pi / teeth
            x1, y1 = cx + math.cos(a) * s * 0.6, cy + math.sin(a) * s * 0.6
            x2, y2 = cx + math.cos(a) * s, cy + math.sin(a) * s
            L((x1, y1), (x2, y2), max(3, int(s * 0.22)))
        pygame.draw.circle(surf, color, (cx, cy), int(s * 0.6), max(2, int(s * 0.14)))
        pygame.draw.circle(surf, color, (cx, cy), int(s * 0.22))
    else:
        draw_text(surf, name, int(s * 1.2), color, (cx, cy), center=True, bold=True)


class Button:
    def __init__(self, rect, label, icon=None, callback=None, theme=None,
                 big=False, accent=False):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.icon = icon            # symbol-text oder icon-name
        self.callback = callback
        self.theme = theme
        self.big = big
        self.accent = accent
        self.hover = 0.0            # 0..1 fuer weichen hover
        self.pressed = False

    def update(self, mouse_pos, dt_):
        target = 1.0 if self.rect.collidepoint(mouse_pos) else 0.0
        self.hover += (target - self.hover) * min(1.0, dt_ * 12)

    def draw(self, surf):
        t = self.theme
        # Hintergrundfarbe interpolieren
        base = t.card
        hov = t.card_hover
        col = tuple(int(lerp(base[i], hov[i], self.hover)) for i in range(3))
        press = -4 if self.pressed else 0
        r = self.rect.inflate(int(self.hover * 6) + press, int(self.hover * 6) + press)
        pygame.draw.rect(surf, col, r, border_radius=18)
        # Rahmen / Akzent
        line = t.accent if self.accent else t.card_line
        pygame.draw.rect(surf, line, r, width=max(1, int(1 + self.hover * 2)),
                         border_radius=18)
        # Icon
        cx = r.centerx
        if self.big:
            if self.icon in APP_ICONS:
                isz = int(r.height * 0.24)
                draw_app_icon(surf, self.icon, cx, r.centery - int(r.height * 0.13),
                              isz, t.accent, t)
                draw_text(surf, self.label, max(15, int(r.height * 0.16)), t.text,
                          (cx, r.centery + int(r.height * 0.30)), center=True, bold=True)
            else:
                icon_size = int(r.height * 0.34)
                draw_text(surf, self.icon or "", icon_size, t.accent,
                          (cx, r.centery - r.height * 0.12), center=True, bold=True)
                draw_text(surf, self.label, max(16, int(r.height * 0.14)), t.text,
                          (cx, r.centery + r.height * 0.26), center=True, bold=True)
        else:
            if self.icon in APP_ICONS:
                draw_app_icon(surf, self.icon, cx, r.centery, int(r.height * 0.34),
                              t.accent, t)
            else:
                label = self.label if not self.icon else f"{self.icon}  {self.label}"
                draw_text(surf, label, 22, t.text, r.center, center=True, bold=True)

    def press(self, pos):
        self.pressed = bool(self.callback and self.rect.collidepoint(pos))
        return self.pressed

    def release(self, pos, allow_unarmed=False):
        was_pressed = self.pressed
        self.pressed = False
        if self.callback and self.rect.collidepoint(pos) and (was_pressed or allow_unarmed):
            self.callback()
            return True
        return False


# ----------------------------------------------------------------------------
# WETTER-ICONS (einfache Vektor-Symbole)
# ----------------------------------------------------------------------------
def draw_weather_icon(surf, kind, cx, cy, scale, theme):
    s = scale
    sun_col = (255, 206, 84)
    cloud_col = (200, 210, 230)
    if kind == "sun":
        for i in range(8):
            a = i * math.pi / 4 + time.time() * 0.4
            x1 = cx + math.cos(a) * s * 0.9
            y1 = cy + math.sin(a) * s * 0.9
            x2 = cx + math.cos(a) * s * 1.3
            y2 = cy + math.sin(a) * s * 1.3
            pygame.draw.line(surf, sun_col, (x1, y1), (x2, y2), max(2, int(s * 0.08)))
        pygame.draw.circle(surf, sun_col, (int(cx), int(cy)), int(s * 0.6))
    elif kind == "partly":
        pygame.draw.circle(surf, sun_col, (int(cx - s * 0.3), int(cy - s * 0.3)), int(s * 0.5))
        _cloud(surf, cx, cy + s * 0.1, s, cloud_col)
    elif kind in ("cloud", "fog"):
        _cloud(surf, cx, cy, s, cloud_col)
    elif kind == "rain":
        _cloud(surf, cx, cy - s * 0.2, s, cloud_col)
        for i in range(3):
            x = cx - s * 0.4 + i * s * 0.4
            pygame.draw.line(surf, theme.accent, (x, cy + s * 0.5),
                             (x - s * 0.15, cy + s * 0.9), max(2, int(s * 0.07)))
    elif kind == "snow":
        _cloud(surf, cx, cy - s * 0.2, s, cloud_col)
        for i in range(3):
            x = cx - s * 0.4 + i * s * 0.4
            pygame.draw.circle(surf, (230, 240, 255), (int(x), int(cy + s * 0.7)), max(2, int(s * 0.08)))
    elif kind == "storm":
        _cloud(surf, cx, cy - s * 0.2, s, (150, 160, 180))
        pts = [(cx, cy + s * 0.4), (cx - s * 0.2, cy + s * 0.4),
               (cx + s * 0.05, cy + s * 0.7), (cx - s * 0.1, cy + s * 0.7),
               (cx + s * 0.2, cy + s * 1.1)]
        pygame.draw.lines(surf, (255, 210, 70), False, pts, max(2, int(s * 0.08)))
    else:
        _cloud(surf, cx, cy, s, cloud_col)


def _cloud(surf, cx, cy, s, col):
    pygame.draw.circle(surf, col, (int(cx - s * 0.4), int(cy)), int(s * 0.4))
    pygame.draw.circle(surf, col, (int(cx + s * 0.4), int(cy)), int(s * 0.4))
    pygame.draw.circle(surf, col, (int(cx), int(cy - s * 0.25)), int(s * 0.5))
    pygame.draw.rect(surf, col, (cx - s * 0.6, cy - s * 0.1, s * 1.2, s * 0.5),
                     border_radius=int(s * 0.25))


# ----------------------------------------------------------------------------
class Screen:
    name = "base"

    def __init__(self, app):
        self.app = app
        self.theme = app.theme
        self.buttons = []
        self._mouse_down_seen = False

    def on_enter(self):
        pass

    def build(self):
        """Buttons/Layout neu aufbauen (z.B. nach Resize)."""
        self.buttons = []
        self._mouse_down_seen = False

    def update(self, dt_):
        mp = pygame.mouse.get_pos()
        for b in self.buttons:
            b.update(mp, dt_)

    def handle_event(self, e):
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            self._mouse_down_seen = True
            for b in self.buttons:
                b.press(e.pos)
            return any(b.pressed for b in self.buttons)
        if e.type == pygame.MOUSEBUTTONUP and e.button == 1:
            allow_unarmed = not self._mouse_down_seen
            self._mouse_down_seen = False
            for b in self.buttons:
                if b.release(e.pos, allow_unarmed=allow_unarmed):
                    for other in self.buttons:
                        other.pressed = False
                    return True
            for b in self.buttons:
                b.pressed = False
        return False

    def draw(self, surf):
        pass


# ----------------------------------------------------------------------------
# HOME-SCREEN
# ----------------------------------------------------------------------------
class HomeScreen(Screen):
    name = "home"

    def build(self):
        self.buttons = []
        app = self.app
        W, H = app.width, app.height

        # Primaere Kacheln (gross, mit Icon)
        primary = [
            ("Uhr", "clock", lambda: app.go("clock")),
            ("Musik", "music", lambda: app.go("music")),
            ("Wetter", "weather", lambda: app.go("weather")),
            ("Timer", "timer", lambda: app.go("timer")),
            ("Wecker", "alarm", lambda: app.go("alarm")),
        ]
        n = len(primary)
        margin = int(W * 0.06)
        gap = int(W * 0.018)
        tile_w = (W - 2 * margin - gap * (n - 1)) // n
        tile_h = min(tile_w, int(H * 0.24))
        top = int(H * 0.50)
        for i, (label, icon, cb) in enumerate(primary):
            x = margin + i * (tile_w + gap)
            self.buttons.append(Button((x, top, tile_w, tile_h), label, icon, cb,
                                       self.theme, big=True))

        # Sekundaere Kacheln (kleiner, dezent)
        secondary = [
            ("Browser", "browser", lambda: app.go("browser")),
            ("Notizen", "notes", lambda: app.go("notes")),
            ("Zufall", "random", lambda: app.start_coin_flip()),
            ("Bello", "bello", lambda: app.bello()),
        ]
        m = len(secondary)
        sw = int(tile_w * 0.78)
        sh = int(H * 0.13)
        sgap = int(W * 0.03)
        total = sw * m + sgap * (m - 1)
        x0 = (W - total) // 2
        top2 = top + tile_h + int(H * 0.03)
        for i, (label, icon, cb) in enumerate(secondary):
            x = x0 + i * (sw + sgap)
            self.buttons.append(Button((x, top2, sw, sh), label, icon, cb,
                                       self.theme, big=True))

        # Einstellungen als kleines Zahnrad oben rechts
        gs = int(H * 0.07)
        self.buttons.append(Button((W - margin - gs, int(H * 0.05), gs, gs),
                                   "", "settings", lambda: app.go("settings"),
                                   self.theme))

    def draw(self, surf):
        app = self.app
        t = self.theme
        W, H = app.width, app.height
        now = dt.datetime.now()

        # Alexa-Ring (pulsierend) oben links
        ring_x, ring_y = int(W * 0.10), int(H * 0.16)
        app.draw_alexa_ring(surf, ring_x, ring_y, int(H * 0.07))

        # Status + Begruessung
        draw_text(surf, app.greeting(), 26, t.muted, (int(W * 0.18), int(H * 0.10)), bold=True)
        draw_text(surf, app.assistant_status, 22, t.accent, (int(W * 0.18), int(H * 0.16)))

        # Grosse Uhr (mittig oben)
        time_str = now.strftime("%H:%M") if app.config["clock_24h"] else now.strftime("%I:%M %p")
        draw_text(surf, time_str, int(H * 0.20), t.text, (int(W * 0.5), int(H * 0.30)),
                  center=True, bold=True)
        date_str = now.strftime("%A, %d. %B %Y")
        draw_text(surf, date_str, 26, t.muted, (int(W * 0.5), int(H * 0.42)), center=True)

        # Mini-Wetter rechts oben
        wd = app.weather.get()
        wx, wy = int(W * 0.86), int(H * 0.13)
        if wd:
            kind = WMO.get(wd["code"], ("?", "cloud"))[1]
            draw_weather_icon(surf, kind, wx - 40, wy, int(H * 0.035), t)
            draw_text(surf, f"{wd['temp']}\u00b0", 40, t.text, (wx + 10, wy - 28), bold=True)
            draw_text(surf, fit_text(wd["city"], 18, 150), 18, t.muted, (wx + 10, wy + 16))
        else:
            draw_text(surf, app.weather.status, 18, t.muted, (wx + 10, wy), right=False)

        # Kacheln
        for b in self.buttons:
            b.draw(surf)


# ----------------------------------------------------------------------------
# CLOCK-SCREEN  (grosse Uhr + Analoganimation)
# ----------------------------------------------------------------------------
class ClockScreen(Screen):
    name = "clock"

    def draw(self, surf):
        app = self.app
        t = self.theme
        W, H = app.width, app.height
        now = dt.datetime.now()

        # ruhiger Hintergrund-Puls
        cx, cy = W // 2, int(H * 0.42)
        r = int(min(W, H) * 0.20)
        pulse = (math.sin(time.time() * 1.2) + 1) / 2
        glow = pygame.Surface((r * 3, r * 3), pygame.SRCALPHA)
        pygame.draw.circle(glow, (*t.accent, int(30 + pulse * 30)), (int(r * 1.5), int(r * 1.5)), r)
        surf.blit(glow, (cx - int(r * 1.5), cy - int(r * 1.5)))

        # Analoguhr-Ring
        pygame.draw.circle(surf, t.card_line, (cx, cy), r, 3)
        for i in range(12):
            a = i * math.pi / 6 - math.pi / 2
            x1 = cx + math.cos(a) * (r - 14)
            y1 = cy + math.sin(a) * (r - 14)
            x2 = cx + math.cos(a) * r
            y2 = cy + math.sin(a) * r
            pygame.draw.line(surf, t.muted, (x1, y1), (x2, y2), 3)
        # Zeiger
        sec = now.second + now.microsecond / 1e6
        minute = now.minute + sec / 60
        hour = now.hour % 12 + minute / 60
        self._hand(surf, cx, cy, (hour / 12) * 2 * math.pi, r * 0.5, 6, t.text)
        self._hand(surf, cx, cy, (minute / 60) * 2 * math.pi, r * 0.75, 4, t.text)
        self._hand(surf, cx, cy, (sec / 60) * 2 * math.pi, r * 0.85, 2, t.accent)
        pygame.draw.circle(surf, t.accent, (cx, cy), 8)

        # Digitale Anzeige
        time_str = now.strftime("%H:%M:%S") if app.config["clock_24h"] else now.strftime("%I:%M:%S %p")
        draw_text(surf, time_str, int(H * 0.13), t.text, (cx, int(H * 0.78)), center=True, bold=True)
        draw_text(surf, now.strftime("%A, %d. %B %Y"), 28, t.muted, (cx, int(H * 0.90)), center=True)

    def _hand(self, surf, cx, cy, ang, length, w, col):
        ang -= math.pi / 2
        x = cx + math.cos(ang) * length
        y = cy + math.sin(ang) * length
        pygame.draw.line(surf, col, (cx, cy), (x, y), w)


# ----------------------------------------------------------------------------
# MUSIC-SCREEN
# ----------------------------------------------------------------------------
class MusicScreen(Screen):
    name = "music"

    def build(self):
        self.buttons = []
        app = self.app
        W, H = app.width, app.height
        bw, bh = 90, 90
        cy = int(H * 0.80)
        gap = 30
        total = bw * 5 + gap * 4
        x0 = (W - total) // 2
        defs = [
            ("|<", app.music.prev),
            ("<<", lambda: None),
            (">||", app.music.toggle_play),
            (">>", lambda: None),
            (">|", app.music.next),
        ]
        for i, (lbl, cb) in enumerate(defs):
            x = x0 + i * (bw + gap)
            self.buttons.append(Button((x, cy, bw, bh), lbl, None, cb, self.theme,
                                       accent=(i == 2)))
        self._bar_heights = [random.random() for _ in range(28)]

    def update(self, dt_):
        super().update(dt_)
        for i in range(len(self._bar_heights)):
            target = random.random()
            self._bar_heights[i] += (target - self._bar_heights[i]) * min(1, dt_ * 6)

    def draw(self, surf):
        app = self.app
        t = self.theme
        W, H = app.width, app.height
        np = app.music.now_playing(app.spotify_pb)

        # Cover / Visualizer links
        cover_size = int(min(W, H) * 0.42)
        cx = int(W * 0.28)
        cy = int(H * 0.40)
        cover_rect = pygame.Rect(0, 0, cover_size, cover_size)
        cover_rect.center = (cx, cy)
        img = app.music.get_album_image(np.get("album_url"), cover_size)
        if img:
            mask = pygame.Surface((cover_size, cover_size), pygame.SRCALPHA)
            pygame.draw.rect(mask, (255, 255, 255), mask.get_rect(), border_radius=20)
            tmp = img.copy()
            tmp.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
            surf.blit(tmp, cover_rect)
        else:
            pygame.draw.rect(surf, t.card, cover_rect, border_radius=20)
            pygame.draw.rect(surf, t.card_line, cover_rect, 2, border_radius=20)
            # animierte Balken im Cover
            # Wichtig: Die Balken duerfen nicht aus der Cover-Box herauslaufen.
            # Vorher war die Breite/Positionierung etwas zu gross, dadurch standen
            # die letzten lila Balken rechts ueber den Rand. Jetzt wird alles in
            # einen inneren Bereich eingepasst und zusaetzlich gegen die Box geclippt.
            n = len(self._bar_heights)
            inner_pad = int(cover_size * 0.12)
            inner = cover_rect.inflate(-inner_pad * 2, -inner_pad * 2)
            gap = max(4, int(cover_size * 0.012))
            bw = max(4, int((inner.width - gap * (n - 1)) / n))
            max_bh = int(inner.height * 0.70)
            for i, h in enumerate(self._bar_heights):
                bh = max(8, int(h * max_bh) + 6)
                bx = inner.left + i * (bw + gap)
                by = inner.centery - bh // 2
                col = tuple(int(lerp(t.accent[k], t.accent2[k], i / max(1, n - 1))) for k in range(3))
                bar_rect = pygame.Rect(bx, by, bw, bh).clip(inner)
                pygame.draw.rect(surf, col, bar_rect, border_radius=4)

        # Info rechts
        rx = int(W * 0.55)
        draw_text(surf, fit_text(np["title"], 44, W * 0.40, bold=True), 44, t.text,
                  (rx, int(H * 0.28)), bold=True)
        draw_text(surf, fit_text(np["artist"], 28, W * 0.40), 28, t.muted, (rx, int(H * 0.37)))
        draw_text(surf, f"Quelle: {app.music.status}", 18, t.accent, (rx, int(H * 0.44)))

        # Fortschrittsbalken
        bar_x, bar_w = rx, int(W * 0.38)
        bar_y = int(H * 0.55)
        pos, dur = np["pos"], max(1, np["dur"])
        prog = max(0, min(1, pos / dur))
        pygame.draw.rect(surf, t.card_line, (bar_x, bar_y, bar_w, 8), border_radius=4)
        pygame.draw.rect(surf, t.accent, (bar_x, bar_y, int(bar_w * prog), 8), border_radius=4)
        draw_text(surf, self._fmt(pos), 18, t.muted, (bar_x, bar_y + 16))
        draw_text(surf, self._fmt(dur), 18, t.muted, (bar_x + bar_w, bar_y + 16), right=True)

        # Lautstaerke
        draw_text(surf, f"Lautstaerke {app.music.volume}%", 18, t.muted, (rx, int(H * 0.64)))
        vx, vw = rx, int(W * 0.38)
        vy = int(H * 0.685)
        pygame.draw.rect(surf, t.card_line, (vx, vy, vw, 6), border_radius=3)
        pygame.draw.rect(surf, t.accent2, (vx, vy, int(vw * app.music.volume / 100), 6),
                         border_radius=3)

        for b in self.buttons:
            b.draw(surf)

    def _fmt(self, s):
        s = int(s)
        return f"{s // 60}:{s % 60:02d}"


# ----------------------------------------------------------------------------
# BROWSER-SCREEN (Schnellzugriffe + YouTube-Hauptfenster)
# ----------------------------------------------------------------------------
class BrowserScreen(Screen):
    name = "browser"

    LINKS = [
        ("YouTube", "https://youtube.com", "YT"),
        ("Google", "https://google.com", "G"),
        ("Maps", "https://maps.google.com", "MAP"),
        ("Wetter", "https://wetter.com", "~"),
        ("Uebersetzer", "https://translate.google.com", "AB"),
        ("Nachrichten", "https://news.google.com", "NEWS"),
    ]

    def build(self):
        self.buttons = []
        app = self.app
        W, H = app.width, app.height
        if app.browser_mode == "youtube":
            self.frame = pygame.Rect(int(W * 0.01), int(H * 0.055),
                                     int(W * 0.98), int(H * 0.925))
            self._build_youtube()
            return
        # Frame
        self.frame = pygame.Rect(int(W * 0.05), int(H * 0.16), int(W * 0.90), int(H * 0.78))
        # Schnellzugriff-Kacheln
        cols = 3
        margin = self.frame.left + 40
        gap = 24
        gw = self.frame.width - 80
        tw = (gw - gap * (cols - 1)) // cols
        th = int(tw * 0.55)
        top = self.frame.top + 90
        for i, (name, url, icon) in enumerate(self.LINKS):
            row, col = divmod(i, cols)
            x = margin + col * (tw + gap)
            y = top + row * (th + gap)
            cb = app.open_youtube if name == "YouTube" \
                 else (lambda u=url, n=name: app.open_url(u, n))
            self.buttons.append(Button((x, y, tw, th), name, icon,
                                       cb, self.theme, big=True))
        # Top-bar Buttons
        self.buttons.append(Button((self.frame.left + 10, self.frame.top + 12, 44, 36),
                                   "<", None, lambda: app.go("home"), self.theme))

    def _build_youtube(self):
        app = self.app
        f = self.frame
        self.buttons.append(Button((f.left + 8, f.top + 10, 42, 32),
                                   "<", None, lambda: app.close_youtube_home(), self.theme))
        self.buttons.append(Button((f.right - 54, f.top + 10, 42, 32),
                                   "X", None, lambda: app.close_youtube_home(),
                                   self.theme, accent=True))
        self.buttons.append(Button((f.right - 210, f.top + 10, 148, 32),
                                   "Schnellwahl", None, lambda: app.set_browser_links(),
                                   self.theme))
        self.buttons.append(Button((f.right - 368, f.top + 10, 138, 32),
                                   "Extern", None,
                                   lambda: app.open_external_url("https://youtube.com"),
                                   self.theme))

    def draw(self, surf):
        app = self.app
        t = self.theme
        f = self.frame
        if app.browser_mode == "youtube":
            self._draw_youtube(surf)
            return
        pygame.draw.rect(surf, t.card, f, border_radius=18)
        pygame.draw.rect(surf, t.card_line, f, 2, border_radius=18)
        # Adressleiste
        ab = pygame.Rect(f.left + 64, f.top + 12, f.width - 200, 36)
        pygame.draw.rect(surf, (15, 18, 32), ab, border_radius=18)
        draw_text(surf, app.browser_url or "https://start", 20, t.muted,
                  (ab.left + 16, ab.centery), center=False)
        draw_text(surf, "* Schnellzugriff", 16, t.muted, (ab.left, ab.centery), right=False)
        draw_text(surf, "Browser", 22, t.accent, (f.right - 100, f.top + 30), center=True, bold=True)
        draw_text(surf, "YouTube bleibt im Hauptfenster sichtbar",
                  18, t.muted, (f.centerx, f.top + 60), center=True)
        for b in self.buttons:
            b.draw(surf)

    def _draw_youtube(self, surf):
        app = self.app
        t = self.theme
        f = self.frame
        pygame.draw.rect(surf, (7, 9, 14), f, border_radius=18)
        pygame.draw.rect(surf, (70, 76, 92), f, 2, border_radius=18)

        header = pygame.Rect(f.left, f.top, f.width, 56)
        pygame.draw.rect(surf, (20, 22, 30), header, border_radius=18)
        pygame.draw.rect(surf, (20, 22, 30), (header.left, header.bottom - 18, header.width, 18))
        logo = pygame.Rect(f.left + 64, f.top + 13, 44, 30)
        pygame.draw.rect(surf, (230, 0, 18), logo, border_radius=8)
        tri = [(logo.left + 20, logo.top + 9), (logo.left + 20, logo.bottom - 9),
               (logo.right - 14, logo.centery)]
        pygame.draw.polygon(surf, (255, 255, 255), tri)
        draw_text(surf, "YouTube", 26, (245, 245, 248), (logo.right + 12, logo.top + 1),
                  bold=True)

        search = pygame.Rect(f.left + int(f.width * 0.36), f.top + 11,
                             int(f.width * 0.31), 32)
        pygame.draw.rect(surf, (8, 10, 16), search, border_radius=19)
        pygame.draw.rect(surf, (72, 76, 88), search, 1, border_radius=19)
        draw_text(surf, f"youtube.com / {app.youtube_section}", 16, (178, 185, 200),
                  (search.left + 18, search.centery), center=False)

        for b in self.buttons:
            b.draw(surf)

        web_rect = pygame.Rect(f.left + 6, header.bottom + 4,
                               f.width - 12, f.bottom - header.bottom - 10)
        app.browser_web_rect = web_rect
        ok = app.show_embedded_web("https://www.youtube.com", web_rect)
        if ok:
            pygame.draw.rect(surf, (72, 204, 255), web_rect, 2, border_radius=10)
        else:
            pygame.draw.rect(surf, (18, 22, 32), web_rect, border_radius=14)
            pygame.draw.rect(surf, (72, 76, 92), web_rect, 2, border_radius=14)
            draw_text(surf, "Echtes YouTube braucht WebKit/PyObjC.",
                      30, (245, 245, 248), (web_rect.centerx, web_rect.centery - 34),
                      center=True, bold=True)
            draw_text(surf, "Installiere die optionalen WebKit-Pakete und starte neu.",
                      22, (172, 182, 202), (web_rect.centerx, web_rect.centery + 6),
                      center=True)
            if app.embedded_web.error:
                draw_text(surf, fit_text(app.embedded_web.error, 18, web_rect.width - 70),
                          18, (255, 184, 70),
                          (web_rect.centerx, web_rect.centery + 42), center=True)


# ----------------------------------------------------------------------------
# WEATHER-SCREEN  (echtes Wetter)
# ----------------------------------------------------------------------------
class WeatherScreen(Screen):
    name = "weather"

    # ---------- Einstieg: je nach Frage anderer Screen ----------
    def draw(self, surf):
        app = self.app
        t = self.theme
        W, H = app.width, app.height
        wd = app.weather.get()
        if not wd:
            draw_text(surf, app.weather.status, 32, t.muted, (W // 2, H // 2), center=True)
            return
        focus = getattr(app, "weather_focus", None)
        mode = (focus or {}).get("mode", "")
        if mode == "Regen":
            self._draw_rain(surf, wd, focus)
        elif mode == "Temperatur":
            self._draw_temp(surf, wd, focus)
        elif mode == "Sonne":
            self._draw_sun(surf, wd, focus)
        elif mode == "Sturm":
            self._draw_storm(surf, wd, focus)
        elif mode == "Wolken":
            self._draw_cloud(surf, wd, focus)
        else:
            self._draw_overview(surf, wd, focus)

    # ---------- Helfer ----------
    def _day_hours(self, wd, idx):
        target = dt.date.today() + dt.timedelta(days=int(idx or 0))
        return [h for h in wd.get("hourly", []) if h["time"].date() == target]

    def _header(self, surf, label, sub, color):
        t = self.theme
        W, H = self.app.width, self.app.height
        draw_text(surf, label, int(H * 0.075), color, (int(W * 0.06), int(H * 0.05)), bold=True)
        draw_text(surf, sub, 24, t.muted, (int(W * 0.06), int(H * 0.155)))

    def _panel(self, surf, rect):
        t = self.theme
        pygame.draw.rect(surf, t.card, rect, border_radius=18)
        pygame.draw.rect(surf, t.card_line, rect, 1, border_radius=18)

    def _bars(self, surf, rect, hours, value_fn, color, max_val=100,
              suffix="%", hot_fn=None, hot_color=None):
        """Stunden-Balkendiagramm mit Achsen-Gitter."""
        t = self.theme
        self._panel(surf, rect)
        if not hours:
            draw_text(surf, "Keine Stundendaten", 22, t.muted, rect.center, center=True)
            return
        pad = 22
        n = len(hours)
        bw = (rect.width - 2 * pad) / n
        base = rect.bottom - 34
        top = rect.top + 30
        max_val = max(1, max_val)
        # Gitterlinien + Achsenbeschriftung (0 / Mitte / Max)
        for frac_line in (0.0, 0.5, 1.0):
            y = int(base - frac_line * (base - top))
            pygame.draw.line(surf, t.card_line, (rect.left + pad, y), (rect.right - pad, y), 1)
            draw_text(surf, f"{int(max_val * frac_line)}{suffix}", 13, t.muted,
                      (rect.left + 6, y - 8))
        vals = [(value_fn(h) or 0) for h in hours]
        peak = max(vals) if vals else 0
        for i, h in enumerate(hours):
            v = value_fn(h) or 0
            x = rect.left + pad + i * bw
            if v > 0:
                frac = max(0.0, min(1.0, v / max_val))
                bh = max(3, int(frac * (base - top)))
                col = hot_color if (hot_fn and hot_fn(h)) else color
                pygame.draw.rect(surf, col, (int(x + 1), int(base - bh),
                                             max(2, int(bw - 2)), bh), border_radius=4)
            hr = h["time"].hour
            if hr % 3 == 0:
                draw_text(surf, f"{hr}", 13, t.muted, (int(x + bw / 2), rect.bottom - 15),
                          center=True)
        # Hinweis, wenn ueberall sehr niedrig (statt leeres Feld)
        if peak < max_val * 0.06:
            draw_text(surf, "durchgehend sehr niedrig", 24, t.muted,
                      (rect.centerx, rect.centery), center=True)

    # ---------- REGEN ----------
    def _draw_rain(self, surf, wd, focus):
        t = self.theme
        W, H = self.app.width, self.app.height
        title = str(focus.get("title", "Heute"))
        self._header(surf, "Regen", f"{wd['city']}  ·  {title}", t.accent)
        draw_weather_icon(surf, "rain", int(W * 0.86), int(H * 0.10), int(H * 0.045), t)

        windows = focus.get("rain_windows") or []
        prob = focus.get("rain_prob", 0)
        mm = focus.get("rain_mm", 0)
        if windows:
            first = windows[0]
            big = f"{first['label']}"
            sub = f"Spitzen-Wahrscheinlichkeit {first.get('prob', prob)}%   ·   gesamt {mm:.1f} mm"
        elif prob:
            big = "Eher trocken"
            sub = f"max. {prob}% Regenchance   ·   {mm:.1f} mm"
        else:
            big = "Trocken"
            sub = "Kein nennenswerter Regen erwartet"
        draw_text(surf, big, int(H * 0.11), t.text, (int(W * 0.06), int(H * 0.26)), bold=True)
        draw_text(surf, sub, 26, t.muted, (int(W * 0.06), int(H * 0.40)))
        if len(windows) > 1:
            more = "  |  ".join(f"{w['label']} ({w.get('prob', '')}%)" for w in windows[1:3])
            draw_text(surf, "Weitere Fenster: " + more, 20, t.accent2, (int(W * 0.06), int(H * 0.47)))

        # Stunden-Balken: Regenwahrscheinlichkeit
        rect = pygame.Rect(int(W * 0.06), int(H * 0.55), int(W * 0.88), int(H * 0.34))
        hours = self._day_hours(wd, focus.get("idx", 0))
        self._bars(surf, rect, hours, lambda h: h.get("precip_prob", 0), t.accent,
                   max_val=100, suffix="%",
                   hot_fn=lambda h: (h.get("precip_prob", 0) >= 50 or h.get("precip", 0) >= 0.2),
                   hot_color=t.accent2)
        draw_text(surf, "Regenwahrscheinlichkeit je Stunde", 18, t.muted,
                  (int(W * 0.06), int(H * 0.52)))

    # ---------- TEMPERATUR ----------
    def _draw_temp(self, surf, wd, focus):
        t = self.theme
        W, H = self.app.width, self.app.height
        idx = focus.get("idx", 0)
        title = str(focus.get("title", "Heute"))
        self._header(surf, "Temperatur", f"{wd['city']}  ·  {title}", t.accent)

        if idx == 0:
            big = f"{wd['temp']}\u00b0"
            sub = f"Gefuehlt {wd['feels']}\u00b0   ·   {focus.get('tmin','-')}\u00b0 bis {focus.get('tmax','-')}\u00b0"
        else:
            big = f"{focus.get('tmax','-')}\u00b0"
            sub = f"Tief {focus.get('tmin','-')}\u00b0   ·   {focus.get('desc','')}"
        draw_text(surf, big, int(H * 0.24), t.text, (int(W * 0.30), int(H * 0.34)),
                  center=True, bold=True)
        draw_weather_icon(surf, focus.get("kind", "cloud"), int(W * 0.62), int(H * 0.30),
                          int(H * 0.08), t)
        draw_text(surf, sub, 26, t.muted, (int(W * 0.06), int(H * 0.55)))

        # Temperaturkurve
        rect = pygame.Rect(int(W * 0.06), int(H * 0.62), int(W * 0.88), int(H * 0.30))
        self._panel(surf, rect)
        hours = self._day_hours(wd, idx)
        temps = [(h, h.get("temp")) for h in hours if h.get("temp") is not None]
        if len(temps) < 2:
            draw_text(surf, "Keine Stundendaten", 22, t.muted, rect.center, center=True)
            return
        lo = min(v for _, v in temps)
        hi = max(v for _, v in temps)
        span = max(1, hi - lo)
        pad = 24
        n = len(temps)
        pts = []
        for i, (h, v) in enumerate(temps):
            x = rect.left + pad + i / (n - 1) * (rect.width - 2 * pad)
            y = rect.bottom - 34 - (v - lo) / span * (rect.height - 60)
            pts.append((int(x), int(y)))
        pygame.draw.lines(surf, t.accent, False, pts, 3)
        for i, (h, v) in enumerate(temps):
            if h["time"].hour % 3 == 0:
                draw_text(surf, f"{h['time'].hour}", 14, t.muted,
                          (pts[i][0], rect.bottom - 16), center=True)
                draw_text(surf, f"{v}\u00b0", 15, t.text, (pts[i][0], pts[i][1] - 16), center=True)

    # ---------- SONNE ----------
    def _draw_sun(self, surf, wd, focus):
        t = self.theme
        W, H = self.app.width, self.app.height
        title = str(focus.get("title", "Heute"))
        sun_col = (255, 206, 84)
        self._header(surf, "Sonne", f"{wd['city']}  ·  {title}", sun_col)

        sr = focus.get("sunrise", "--:--")
        ss = focus.get("sunset", "--:--")
        # Bogen Sonnenaufgang -> Sonnenuntergang
        cx, cy = int(W * 0.5), int(H * 0.52)
        rx, ry = int(W * 0.34), int(H * 0.22)
        prev = None
        for deg in range(180, 361, 6):
            a = math.radians(deg)
            p = (int(cx + math.cos(a) * rx), int(cy + math.sin(a) * ry))
            if prev:
                pygame.draw.line(surf, t.card_line, prev, p, 3)
            prev = p
        # Sonnenposition nach aktueller Zeit
        frac = self._daytime_fraction(sr, ss)
        if frac is not None:
            a = math.radians(180 + frac * 180)
            sx, sy = int(cx + math.cos(a) * rx), int(cy + math.sin(a) * ry)
            pygame.draw.circle(surf, sun_col, (sx, sy), 16)
        draw_text(surf, sr, 30, t.text, (cx - rx, cy + 30), center=True, bold=True)
        draw_text(surf, "Aufgang", 18, t.muted, (cx - rx, cy + 58), center=True)
        draw_text(surf, ss, 30, t.text, (cx + rx, cy + 30), center=True, bold=True)
        draw_text(surf, "Untergang", 18, t.muted, (cx + rx, cy + 58), center=True)

        windows = focus.get("sun_windows") or []
        if windows:
            wtxt = "  ·  ".join(w["label"] for w in windows[:3])
            draw_text(surf, "Beste Sonne: " + wtxt, 24, sun_col,
                      (int(W * 0.06), int(H * 0.75)), bold=True)
        else:
            draw_text(surf, "Kaum klare Sonnenfenster", 24, t.muted,
                      (int(W * 0.06), int(H * 0.75)))
        draw_text(surf, f"{focus.get('sunshine_hours', 0)} Sonnenstunden", 22, t.muted,
                  (int(W * 0.06), int(H * 0.82)))
        # UV-Anzeige
        self._uv_gauge(surf, pygame.Rect(int(W * 0.5), int(H * 0.80), int(W * 0.44), 40),
                       focus.get("uv", 0))

    def _uv_gauge(self, surf, rect, uv):
        t = self.theme
        draw_text(surf, f"UV {uv}", 20, t.text, (rect.left, rect.top - 4), bold=True)
        bar = pygame.Rect(rect.left, rect.top + 22, rect.width, 12)
        pygame.draw.rect(surf, t.card_line, bar, border_radius=6)
        frac = max(0.0, min(1.0, uv / 11.0))
        col = (60, 200, 120) if uv < 3 else (255, 200, 60) if uv < 6 else \
              (255, 140, 60) if uv < 8 else (255, 90, 90)
        pygame.draw.rect(surf, col, (bar.left, bar.top, int(bar.width * frac), 12),
                         border_radius=6)

    def _daytime_fraction(self, sr, ss):
        try:
            now = dt.datetime.now()
            sh, sm = map(int, sr.split(":"))
            eh, em = map(int, ss.split(":"))
            start = sh * 60 + sm
            end = eh * 60 + em
            cur = now.hour * 60 + now.minute
            if end <= start:
                return None
            return max(0.0, min(1.0, (cur - start) / (end - start)))
        except Exception:
            return None

    # ---------- STURM ----------
    def _draw_storm(self, surf, wd, focus):
        t = self.theme
        W, H = self.app.width, self.app.height
        title = str(focus.get("title", "Heute"))
        warn = focus.get("storm_windows") or focus.get("gust", 0) >= 65
        color = (255, 90, 90) if warn else t.accent
        self._header(surf, "Sturm & Wind", f"{wd['city']}  ·  {title}", color)
        draw_weather_icon(surf, "storm" if warn else "cloud", int(W * 0.86),
                          int(H * 0.10), int(H * 0.045), t)

        gust = focus.get("gust", 0)
        draw_text(surf, f"{gust} km/h", int(H * 0.16), t.text,
                  (int(W * 0.06), int(H * 0.28)), bold=True)
        draw_text(surf, "Spitzenboeen", 24, t.muted, (int(W * 0.06), int(H * 0.45)))
        windows = focus.get("storm_windows") or []
        if windows:
            wtxt = "  ·  ".join(w["label"] for w in windows[:3])
            draw_text(surf, "Gewitter/Boeen: " + wtxt, 24, color,
                      (int(W * 0.06), int(H * 0.52)), bold=True)
        elif warn:
            draw_text(surf, "Stuermische Boeen moeglich", 24, color,
                      (int(W * 0.06), int(H * 0.52)), bold=True)
        else:
            draw_text(surf, "Kein Sturm-Signal", 24, t.muted, (int(W * 0.06), int(H * 0.52)))

        rect = pygame.Rect(int(W * 0.06), int(H * 0.60), int(W * 0.88), int(H * 0.32))
        hours = self._day_hours(wd, focus.get("idx", 0))
        gmax = max([h.get("gust", 0) for h in hours] + [60])
        self._bars(surf, rect, hours, lambda h: h.get("gust", 0), color,
                   max_val=gmax, suffix=" km/h",
                   hot_fn=lambda h: h.get("gust", 0) >= 65, hot_color=(255, 90, 90))
        draw_text(surf, "Windboeen je Stunde", 18, t.muted, (int(W * 0.06), int(H * 0.57)))

    # ---------- WOLKEN ----------
    def _draw_cloud(self, surf, wd, focus):
        t = self.theme
        W, H = self.app.width, self.app.height
        title = str(focus.get("title", "Heute"))
        cloud_col = (200, 210, 230)
        self._header(surf, "Bewoelkung", f"{wd['city']}  ·  {title}", t.accent)
        draw_weather_icon(surf, "cloud", int(W * 0.86), int(H * 0.10), int(H * 0.045), t)

        avg = focus.get("cloud_avg")
        big = f"{avg}%" if avg is not None else "--"
        draw_text(surf, big, int(H * 0.16), t.text, (int(W * 0.06), int(H * 0.28)), bold=True)
        draw_text(surf, "Wolkendecke im Schnitt", 24, t.muted, (int(W * 0.06), int(H * 0.45)))
        windows = focus.get("sun_windows") or []
        if windows:
            draw_text(surf, "Freundlichste Phase: " + windows[0]["label"], 24,
                      (255, 206, 84), (int(W * 0.06), int(H * 0.52)), bold=True)
        else:
            draw_text(surf, "Kein klares Aufklaren in Sicht", 24, t.muted,
                      (int(W * 0.06), int(H * 0.52)))

        rect = pygame.Rect(int(W * 0.06), int(H * 0.60), int(W * 0.88), int(H * 0.32))
        hours = self._day_hours(wd, focus.get("idx", 0))
        self._bars(surf, rect, hours, lambda h: h.get("cloud"), cloud_col, max_val=100, suffix="%")
        draw_text(surf, "Bewoelkung je Stunde", 18, t.muted, (int(W * 0.06), int(H * 0.57)))

    # ---------- UEBERSICHT (Standard) ----------
    def _draw_overview(self, surf, wd, focus):
        t = self.theme
        W, H = self.app.width, self.app.height
        text, kind = WMO.get(wd["code"], ("Unbekannt", "cloud"))
        draw_weather_icon(surf, kind, int(W * 0.22), int(H * 0.28), int(H * 0.09), t)
        draw_text(surf, f"{wd['temp']}\u00b0", int(H * 0.20), t.text,
                  (int(W * 0.45), int(H * 0.28)), center=True, bold=True)
        draw_text(surf, text, 36, t.muted, (int(W * 0.62), int(H * 0.22)))
        draw_text(surf, wd["city"], 30, t.accent, (int(W * 0.62), int(H * 0.30)), bold=True)
        draw_text(surf, f"Gefuehlt {wd['feels']}\u00b0   Wind {wd['wind']} km/h   "
                        f"Luftf. {wd['humidity']}%",
                  22, t.muted, (int(W * 0.62), int(H * 0.37)))

        fc = wd["forecast"]
        n = len(fc)
        margin = int(W * 0.06)
        gap = 18
        cw = (W - margin * 2 - gap * (n - 1)) // max(1, n)
        top = int(H * 0.50)
        ch = int(H * 0.38)
        for i, day in enumerate(fc):
            x = margin + i * (cw + gap)
            r = pygame.Rect(x, top, cw, ch)
            pygame.draw.rect(surf, t.card, r, border_radius=16)
            pygame.draw.rect(surf, t.card_line, r, 1, border_radius=16)
            label = "Heute" if i == 0 else day["day"]
            draw_text(surf, label, 24, t.text, (r.centerx, r.top + 30), center=True, bold=True)
            k = WMO.get(day["code"], ("?", "cloud"))[1]
            draw_weather_icon(surf, k, r.centerx, r.centery, int(ch * 0.13), t)
            draw_text(surf, f"{day['tmax']}\u00b0", 26, t.text,
                      (r.centerx - 24, r.bottom - 40), center=True, bold=True)
            draw_text(surf, f"{day['tmin']}\u00b0", 22, t.muted,
                      (r.centerx + 24, r.bottom - 40), center=True)


# ----------------------------------------------------------------------------
# TIMER-SCREEN
# ----------------------------------------------------------------------------
class TimerScreen(Screen):
    name = "timer"

    def build(self):
        self.buttons = []
        app = self.app
        W, H = app.width, app.height
        bw, bh = 150, 70
        gap = 24
        defs = [
            ("Start", app.timer_start),
            ("Pause", app.timer_pause),
            ("Stop", app.timer_stop),
        ]
        total = bw * 3 + gap * 2
        x0 = (W - total) // 2
        y = int(H * 0.70)
        for i, (lbl, cb) in enumerate(defs):
            self.buttons.append(Button((x0 + i * (bw + gap), y, bw, bh), lbl, None, cb,
                                       self.theme, accent=(i == 0)))
        # +1 / +5 / +10 min
        presets = [1, 5, 10]
        pw = 110
        tot2 = pw * 3 + gap * 2
        x0b = (W - tot2) // 2
        yb = int(H * 0.84)
        for i, m in enumerate(presets):
            self.buttons.append(Button((x0b + i * (pw + gap), yb, pw, 56),
                                       f"+{m} min", None,
                                       (lambda mm=m: app.timer_add(mm)), self.theme))

    def draw(self, surf):
        app = self.app
        t = self.theme
        W, H = app.width, app.height
        remaining = app.timer_remaining()
        col = t.danger if app.timer_fired else t.text
        big = self._fmt(remaining)
        draw_text(surf, big, int(H * 0.26), col, (W // 2, int(H * 0.34)), center=True, bold=True)
        # Fortschrittsring
        cx, cy = W // 2, int(H * 0.34)
        r = int(min(W, H) * 0.22)
        if app.timer_total > 0:
            prog = 1 - max(0, remaining) / app.timer_total
        else:
            prog = 0
        pygame.draw.circle(surf, t.card_line, (cx, cy), r, 6)
        self._arc(surf, cx, cy, r, prog, t.accent)
        status = "Timer fertig! Sag Alexa stop." if app.timer_fired else \
                 ("Laeuft" if app.timer_active else "Bereit")
        draw_text(surf, status, 28, t.accent, (W // 2, int(H * 0.58)), center=True)
        for b in self.buttons:
            b.draw(surf)

    def _arc(self, surf, cx, cy, r, prog, col):
        if prog <= 0:
            return
        steps = int(prog * 120)
        for i in range(steps):
            a = -math.pi / 2 + (i / 120) * 2 * math.pi
            x = cx + math.cos(a) * r
            y = cy + math.sin(a) * r
            pygame.draw.circle(surf, col, (int(x), int(y)), 4)

    def _fmt(self, s):
        s = max(0, int(s))
        return f"{s // 60:02d}:{s % 60:02d}"


# ----------------------------------------------------------------------------
# ALARM / WECKER-SCREEN
# ----------------------------------------------------------------------------
class AlarmScreen(Screen):
    name = "alarm"

    def build(self):
        self.buttons = []
        app = self.app
        W, H = app.width, app.height
        bw, bh = 160, 64
        gap = 24
        x0 = (W - (bw * 2 + gap)) // 2
        y = int(H * 0.72)
        self.buttons.append(Button((x0, y, bw, bh), "Wecker aus", None,
                                   app.alarm_off, self.theme, accent=False))
        self.buttons.append(Button((x0 + bw + gap, y, bw, bh), "Alarm stoppen", None,
                                   app.alarm_dismiss, self.theme, accent=True))
        # Schnell-Presets
        presets = ["06:30", "07:00", "07:30", "08:00", "09:00"]
        pw = 110
        tot = pw * len(presets) + gap * (len(presets) - 1)
        x0b = (W - tot) // 2
        yb = int(H * 0.85)
        for i, p in enumerate(presets):
            self.buttons.append(Button((x0b + i * (pw + gap), yb, pw, 52), p, None,
                                       (lambda pp=p: app.set_alarm_str(pp)), self.theme))

    def draw(self, surf):
        app = self.app
        t = self.theme
        W, H = app.width, app.height
        if app.alarm_ringing:
            pulse = (math.sin(time.time() * 8) + 1) / 2
            draw_text(surf, "WECKER!", int(H * 0.18), t.danger, (W // 2, int(H * 0.34)),
                      center=True, bold=True, alpha=int(120 + pulse * 135))
        else:
            if app.alarm_time:
                draw_text(surf, app.alarm_time, int(H * 0.24), t.text,
                          (W // 2, int(H * 0.34)), center=True, bold=True)
                draw_text(surf, "Wecker aktiv", 30, t.good, (W // 2, int(H * 0.56)), center=True)
            else:
                draw_text(surf, "--:--", int(H * 0.24), t.muted, (W // 2, int(H * 0.34)),
                          center=True, bold=True)
                draw_text(surf, "Kein Wecker gestellt", 28, t.muted,
                          (W // 2, int(H * 0.56)), center=True)
        for b in self.buttons:
            b.draw(surf)


# ----------------------------------------------------------------------------
# ZUFALLS-ANIMATIONEN (Muenze / Zahl)
# ----------------------------------------------------------------------------
class RandomScreen(Screen):
    name = "random"

    def __init__(self, app):
        super().__init__(app)
        self._particles = []
        self._landed = False
        self._flash_alpha = 0

    def on_enter(self):
        """Zustand zuruecksetzen wenn Screen betreten wird (neue Animation)."""
        self._particles = []
        self._landed = False
        self._flash_alpha = 0

    def build(self):
        self.buttons = []
        app = self.app
        W, H = app.width, app.height
        bw, bh = int(W * 0.22), int(H * 0.09)
        y = int(H * 0.82)
        gap = int(W * 0.04)
        x0 = (W - bw * 2 - gap) // 2
        self.buttons.append(Button((x0, y, bw, bh), "Muenze", "", lambda: app.start_coin_flip(), self.theme))
        self.buttons.append(Button((x0 + bw + gap, y, bw, bh), "Zahl 1-5", "", lambda: app.start_number_roll(1, 5), self.theme))

    def _spawn_particles(self, cx, cy, kind, t):
        """Partikel-Burst beim Landen der Muenze / Zahl."""
        self._particles = []
        for _ in range(32):
            angle = random.uniform(0, math.tau)
            speed = random.uniform(1.5, 7.0)
            if kind == "coin":
                palette = [(255, 218, 50), (255, 195, 30), (255, 240, 130), (240, 170, 20), (255, 255, 180)]
            else:
                ac, ac2 = t.accent, t.accent2
                palette = [
                    ac, ac2,
                    (min(255, ac[0] + 70), min(255, ac[1] + 70), min(255, ac[2] + 70)),
                    (min(255, ac2[0] + 70), min(255, ac2[1] + 70), min(255, ac2[2] + 70)),
                ]
            self._particles.append({
                "x": float(cx), "y": float(cy),
                "vx": math.cos(angle) * speed,
                "vy": math.sin(angle) * speed - random.uniform(0.5, 4.0),
                "color": random.choice(palette),
                "size": random.uniform(3.0, 8.0),
                "life": 1.0,
                "decay": random.uniform(0.010, 0.028),
            })

    def update(self, dt_):
        super().update(dt_)
        anim = self.app.random_anim or {}
        kind = anim.get("type", "coin")
        elapsed = time.time() - anim.get("start", time.time())
        duration = anim.get("duration", 2.4)
        progress = min(1.0, elapsed / max(0.1, duration))
        W, H = self.app.width, self.app.height
        cx = W // 2
        cy = int(H * 0.50)

        # Landungs-Schwellwert: Muenze 75%, Zahl 82%
        land_thresh = 0.75 if kind == "coin" else 0.82
        if progress >= land_thresh and not self._landed:
            self._landed = True
            self._spawn_particles(cx, cy, kind, self.theme)
            self._flash_alpha = 155

        # Partikel aktualisieren (Schwerkraft)
        for p in self._particles:
            p["x"] += p["vx"]
            p["y"] += p["vy"]
            p["vy"] += 0.20          # Schwerkraft
            p["vx"] *= 0.98          # leichte Luftreibung
            p["life"] -= p["decay"]
        self._particles = [p for p in self._particles if p["life"] > 0]

        # Flash ausblenden
        if self._flash_alpha > 0:
            self._flash_alpha = max(0, self._flash_alpha - 10)

    # ------------------------------------------------------------------
    def _draw_coin(self, surf, cx, cy, progress, elapsed, result, t):
        """3-D Muenzwurf: Wurfparabel + Perspective-Squish + Shading."""
        W, H = self.app.width, self.app.height

        # Spin: ease-out-cubic, 10 Halbumdrehungen → endet face-up (cos=1)
        total_half = 10.0
        spin_p = min(1.0, progress / 0.85)
        ease_spin = 1.0 - (1.0 - spin_p) ** 3
        half_turns = total_half * ease_spin
        angle = half_turns * math.pi
        squeeze = math.cos(angle)        # -1..+1 → Breite relativ zu Durchmesser
        face_up = (int(half_turns) % 2 == 0)   # gerade = Vorderseite oben

        # Wurfparabel: Muenze steigt und faellt
        arc_h = int(H * 0.23)
        fly_phase = min(1.0, progress / 0.76)
        arc_offset = int(-arc_h * 4.0 * fly_phase * (1.0 - fly_phase))

        # Kleiner Aufprall-Bounce nach dem Landen
        bounce_y = 0
        if 0.75 < progress <= 0.91:
            bp = (progress - 0.75) / 0.16
            bounce_y = int(-18 * abs(math.sin(bp * math.pi * 2.5)) * (1.0 - bp))

        coin_y = cy + arc_offset + bounce_y
        coin_r  = 110

        # Dynamischer Schatten (klein wenn hoch, gross wenn nah am Boden)
        shad_scale = 0.20 + 0.80 * fly_phase
        shad_w = max(4, int(coin_r * 1.7 * shad_scale))
        shad_h = max(2, int(coin_r * 0.26 * shad_scale))
        shad_alpha = int(95 * shad_scale)
        if shad_w > 4 and shad_h > 2:
            shad = pygame.Surface((shad_w * 2, shad_h * 2), pygame.SRCALPHA)
            pygame.draw.ellipse(shad, (0, 0, 0, shad_alpha), shad.get_rect())
            surf.blit(shad, (cx - shad_w, cy + coin_r - shad_h + 4))

        coin_w = max(5, int(coin_r * 2 * abs(squeeze)))
        if coin_w < 5:
            return   # Muenze steht gerade hochkant – unsichtbar

        rect = pygame.Rect(cx - coin_w // 2, coin_y - coin_r, coin_w, coin_r * 2)

        # Goldseite (Kopf) vs. Silberseite (Zahl) – je nach squeeze-Vorzeichen
        if squeeze >= 0:
            base_c  = (188, 148, 20)
            mid_c   = (238, 190, 58)
            hi_c    = (255, 235, 130)
            edge_c  = (148, 114, 10)
            text_c  = (65, 44, 6)
        else:
            base_c  = (130, 142, 156)
            mid_c   = (182, 192, 205)
            hi_c    = (225, 232, 242)
            edge_c  = (105, 118, 132)
            text_c  = (52, 62, 76)

        # Basis-Ellipse
        pygame.draw.ellipse(surf, base_c, rect)

        # Heller Mittelteil (simuliert Rundung)
        ir = pygame.Rect(rect.x + coin_w // 6,
                         rect.y + coin_r * 2 // 6,
                         coin_w * 2 // 3,
                         coin_r * 2 * 2 // 3)
        if ir.width > 2 and ir.height > 2:
            pygame.draw.ellipse(surf, mid_c, ir)

        # Spekularer Glanz-Fleck oben-links
        if coin_w > 24:
            gw = max(4, coin_w // 3)
            gh = max(4, coin_r * 2 // 5)
            gs = pygame.Surface((gw, gh), pygame.SRCALPHA)
            pygame.draw.ellipse(gs, (*hi_c, 145), (0, 0, gw, gh))
            surf.blit(gs, (rect.x + coin_w // 9, rect.y + coin_r * 2 // 9))

        # Muenzrand (aussen)
        pygame.draw.ellipse(surf, edge_c, rect, max(2, coin_w // 26))

        # Innerer Praege-Ring (wie echte Muenzen)
        inner_ring = rect.inflate(-max(4, coin_w // 10), -max(4, coin_r * 2 // 10))
        if inner_ring.width > 8 and inner_ring.height > 8:
            pygame.draw.ellipse(surf, edge_c, inner_ring, max(1, coin_w // 40))

        # Beschriftung: "?" waehrend Flug, voller Text nach Landen
        sq_ratio = abs(squeeze)
        lbl_alpha = int(255 * max(0.0, (sq_ratio - 0.22) / 0.52))
        if lbl_alpha > 12:
            if not self._landed:
                label_top = "?"
                label_bot = None
            else:
                if face_up:
                    label_top = result.upper()          # "KOPF" oder "ZAHL"
                    label_bot = "\u2605" if result == "Kopf" else "#"
                else:
                    other     = "ZAHL" if result == "Kopf" else "KOPF"
                    label_top = other
                    label_bot = "#" if result == "Kopf" else "\u2605"

            fs_main = max(14, int(coin_r * 0.38 * sq_ratio))
            fs_sub  = max(10, int(coin_r * 0.24 * sq_ratio))
            y_main  = coin_y - (int(fs_sub * 0.55) if label_bot else 0)
            draw_text(surf, label_top, fs_main, text_c, (cx, y_main),
                      center=True, bold=True, alpha=lbl_alpha)
            if label_bot:
                draw_text(surf, label_bot, fs_sub, edge_c,
                          (cx, y_main + int(fs_main * 0.72)),
                          center=True, bold=False, alpha=lbl_alpha)

        # Ergebnis-Zeile nach abgeschlossener Animation
        if progress >= 1.0:
            draw_text(surf, f"Ergebnis: {result}", 46, t.accent,
                      (W // 2, int(H * 0.74)), center=True, bold=True)

    # ------------------------------------------------------------------
    def _draw_number(self, surf, cx, cy, progress, elapsed, result, lo, hi, t):
        """Slot-Machine-Scrollen → Bounce-Landing + Glow-Ring."""
        W, H = self.app.width, self.app.height
        bw, bh = 300, 220
        box = pygame.Rect(cx - bw // 2, cy - bh // 2, bw, bh)
        pygame.draw.rect(surf, t.card, box, border_radius=32)

        # Glowing Ring: pulsiert waehrend Scrollen, leuchtet beim Ergebnis
        if progress < 0.82:
            pulse = 0.55 + 0.45 * math.sin(elapsed * 7.5)
            ring_alpha = int(160 + 95 * pulse)
            ring_col = t.accent
        else:
            land_p = (progress - 0.82) / 0.18
            ring_alpha = min(255, int(200 + 55 * land_p))
            ring_col = (int(lerp(t.accent[0], t.good[0], land_p)),
                        int(lerp(t.accent[1], t.good[1], land_p)),
                        int(lerp(t.accent[2], t.good[2], land_p)))
        rs = pygame.Surface((bw + 20, bh + 20), pygame.SRCALPHA)
        pygame.draw.rect(rs, (*ring_col, ring_alpha),
                         (0, 0, bw + 20, bh + 20), width=5, border_radius=36)
        surf.blit(rs, (cx - bw // 2 - 10, cy - bh // 2 - 10))

        # Clip-Region damit Zahlen nicht aus der Box herausragen
        clip_old = surf.get_clip()
        surf.set_clip(box.inflate(-6, -6))

        if progress < 0.82:
            # Scroll-Geschwindigkeit: schnell → langsam (ease-out)
            roll_speed = 24.0 * (1.0 - ease(min(1.0, progress / 0.82)))
            slot_t = elapsed * (roll_speed + 0.5)
            rng = max(1, hi - lo)
            idx = int(slot_t)
            frac = slot_t - idx          # 0..1 innerhalb aktuellen Frames
            shown  = lo + idx % (rng + 1)
            prev   = lo + (idx - 1) % (rng + 1)

            # Aktuelle Zahl kommt von unten
            y_off = int(bh * 0.38 * (1.0 - frac))
            draw_text(surf, str(shown), 112, t.text,
                      (cx, cy + y_off), center=True, bold=True)
            # Vorherige Zahl geht nach oben
            prev_alpha = int(255 * (1.0 - frac))
            draw_text(surf, str(prev), 112, t.muted,
                      (cx, cy + y_off - int(bh * 0.40)), center=True,
                      bold=True, alpha=prev_alpha)
        else:
            # Ergebnis mit Overshoot-Bounce-Scale
            land_p = (progress - 0.82) / 0.18
            bounce = 1.0 + 0.32 * math.sin(land_p * math.pi) * max(0.0, 1.0 - land_p * 0.85)
            fs = max(72, int(118 * bounce))
            factor = min(1.0, land_p * 1.6)
            rc = (int(lerp(t.text[0], t.accent[0], factor)),
                  int(lerp(t.text[1], t.accent[1], factor)),
                  int(lerp(t.text[2], t.accent[2], factor)))
            draw_text(surf, str(result), fs, rc, (cx, cy), center=True, bold=True)

        surf.set_clip(clip_old)

        # Unterschrift nach Abschluss
        if progress >= 1.0:
            draw_text(surf, "Das ist deine Zahl!", 30, t.muted,
                      (W // 2, int(H * 0.74)), center=True)

    # ------------------------------------------------------------------
    def draw(self, surf):
        app = self.app
        t = self.theme
        W, H = app.width, app.height
        anim = app.random_anim or {}
        kind    = anim.get("type", "coin")
        result  = anim.get("result", "?")
        start   = anim.get("start", time.time())
        elapsed = time.time() - start
        duration = anim.get("duration", 2.4)
        progress = max(0.0, min(1.0, elapsed / max(0.1, duration)))

        # Titel
        draw_text(surf, "Zufall", 48, t.text,
                  (int(W * 0.5), int(H * 0.10)), center=True, bold=True)

        # Dynamischer Untertitel
        if kind == "coin":
            sub = "Ich werfe eine Muenze..." if progress < 0.82 else f"Die Muenze zeigt: {result}"
        else:
            lo, hi = anim.get("range", (1, 5))
            sub = f"Ich sage eine Zahl von {lo} bis {hi}..." if progress < 0.82 else f"Die Zahl ist: {result}"
        draw_text(surf, sub, 28, t.muted,
                  (int(W * 0.5), int(H * 0.21)), center=True)

        # Weiss-Flash beim Aufprall
        if self._flash_alpha > 0:
            fl = pygame.Surface((W, H), pygame.SRCALPHA)
            fl.fill((255, 255, 255, self._flash_alpha))
            surf.blit(fl, (0, 0))

        # Hauptanimation
        cx, cy = W // 2, int(H * 0.50)
        if kind == "coin":
            self._draw_coin(surf, cx, cy, progress, elapsed, result, t)
        else:
            lo, hi = anim.get("range", (1, 5))
            self._draw_number(surf, cx, cy, progress, elapsed, result, lo, hi, t)

        # Partikel
        for p in self._particles:
            s = max(1, int(p["size"] * p["life"]))
            ps = pygame.Surface((s * 2, s * 2), pygame.SRCALPHA)
            pygame.draw.circle(ps, (*p["color"], int(255 * p["life"])), (s, s), s)
            surf.blit(ps, (int(p["x"]) - s, int(p["y"]) - s))

        # Buttons
        for b in self.buttons:
            b.draw(surf)

# ----------------------------------------------------------------------------
# NOTIZEN-SCREEN
# ----------------------------------------------------------------------------
class NotesScreen(Screen):
    name = "notes"

    def draw(self, surf):
        app = self.app
        t = self.theme
        W, H = app.width, app.height
        draw_text(surf, "Notizen", 40, t.text, (int(W * 0.06), int(H * 0.10)), bold=True)
        draw_text(surf, 'Tippe: "notiz <text>" um etwas zu speichern',
                  20, t.muted, (int(W * 0.06), int(H * 0.18)))
        y = int(H * 0.27)
        if not app.notes:
            draw_text(surf, "Noch keine Notizen.", 24, t.muted, (int(W * 0.06), y))
        for i, note in enumerate(app.notes[-10:]):
            r = pygame.Rect(int(W * 0.06), y, int(W * 0.88), 52)
            pygame.draw.rect(surf, t.card, r, border_radius=12)
            draw_text(surf, fit_text(f"{i+1}. {note}", 24, r.width - 30),
                      24, t.text, (r.left + 18, r.centery), center=False)
            y += 60


# ----------------------------------------------------------------------------
# SETTINGS-SCREEN
# ----------------------------------------------------------------------------
class SettingsScreen(Screen):
    name = "settings"

    def build(self):
        self.buttons = []
        app = self.app
        W, H = app.width, app.height
        items = [
            (f"Vollbild: {'AN' if app.fullscreen else 'AUS'}", app.toggle_fullscreen),
            (f"Nachtmodus: {'AN' if self.theme.night else 'AUS'}", app.toggle_night),
            (f"Alexa-Sprachmodus: {'AN' if app.voice.listening else ('AUS' if HAVE_SR else 'NICHT VERFUEGBAR')}",
             app.toggle_wakeword),
            (f"Sprachausgabe: {'AN' if app.voice.enabled else 'NICHT VERFUEGBAR'}",
             app.toggle_voice),
            (f"Lautstaerke: {app.music.volume}%  (-/+)", lambda: None),
            ("Wetter aktualisieren", app.weather.refresh),
            ("Zurueck zum Home", lambda: app.go("home")),
        ]
        bw = int(W * 0.6)
        bh = 64
        x = (W - bw) // 2
        y = int(H * 0.22)
        for lbl, cb in items:
            self.buttons.append(Button((x, y, bw, bh), lbl, None, cb, self.theme))
            y += bh + 16

    def on_enter(self):
        self.build()  # Labels aktualisieren

    def draw(self, surf):
        app = self.app
        t = self.theme
        W, H = app.width, app.height
        draw_text(surf, "Einstellungen", 44, t.text, (W // 2, int(H * 0.12)),
                  center=True, bold=True)
        # Status-Infos
        info = [
            f"Spotify: {app.music.status}",
            f"Mikrofon: {'verfuegbar' if HAVE_SR else 'nicht installiert'}",
            f"TTS: {'verfuegbar' if app.voice.enabled else 'nicht verfuegbar'}",
        ]
        draw_text(surf, "   |   ".join(info), 18, t.muted, (W // 2, int(H * 0.90)), center=True)
        for b in self.buttons:
            b.draw(surf)


# ----------------------------------------------------------------------------
# STARTANIMATION / SPLASH
# ----------------------------------------------------------------------------
class SplashScreen(Screen):
    name = "splash"

    def on_enter(self):
        self.start = time.time()

    def draw(self, surf):
        app = self.app
        t = self.theme
        W, H = app.width, app.height
        elapsed = time.time() - self.start
        prog = min(1, elapsed / 1.8)
        app.draw_alexa_ring(surf, W // 2, int(H * 0.42), int(H * 0.10))
        draw_text(surf, "Echo Show", int(H * 0.10), t.text, (W // 2, int(H * 0.62)),
                  center=True, bold=True, alpha=int(255 * ease(prog)))
        draw_text(surf, "Notebook Edition", 24, t.muted, (W // 2, int(H * 0.72)),
                  center=True, alpha=int(255 * ease(prog)))
        # Ladebalken
        bw = int(W * 0.3)
        bx = (W - bw) // 2
        by = int(H * 0.80)
        pygame.draw.rect(surf, t.card_line, (bx, by, bw, 6), border_radius=3)
        pygame.draw.rect(surf, t.accent, (bx, by, int(bw * prog), 6), border_radius=3)
        if elapsed > 2.2:
            app.go("home")


# ----------------------------------------------------------------------------
# COMMAND-PARSER  (versteht "Alexa, ..."-Befehle)
# ----------------------------------------------------------------------------
import re

# --- sichere Arithmetik-Auswertung (kein eval auf beliebigem Code) ---
_CALC_OPS = {
    _ast.Add: _operator.add, _ast.Sub: _operator.sub, _ast.Mult: _operator.mul,
    _ast.Div: _operator.truediv, _ast.Pow: _operator.pow, _ast.Mod: _operator.mod,
    _ast.FloorDiv: _operator.floordiv, _ast.USub: _operator.neg, _ast.UAdd: _operator.pos,
}


def _safe_eval(node):
    if isinstance(node, _ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, getattr(_ast, "Num", ())):  # Py<3.8 Kompatibilitaet
        return node.n
    if isinstance(node, _ast.BinOp) and type(node.op) in _CALC_OPS:
        return _CALC_OPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, _ast.UnaryOp) and type(node.op) in _CALC_OPS:
        return _CALC_OPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError("nicht erlaubt")


class CommandParser:
    JOKES = [
        "Warum koennen Skelette schlecht luegen? Man durchschaut sie sofort.",
        "Ich wollte einen Witz ueber Zeit machen, aber der Timing war schlecht.",
        "Was macht ein Pirat am Computer? Er drueckt die Enter-Taste.",
        "Warum war der Roboter muede? Er hatte einen harten Cache.",
    ]
    SMALLTALK = {
        "hallo": "Hallo! Wie kann ich dir helfen?",
        "hi": "Hi! Was kann ich fuer dich tun?",
        "wie geht": "Mir geht es bestens, danke der Nachfrage!",
        "wie heisst": "Ich bin dein Echo Show fuers Notebook.",
        "was kannst du": "Ich kann Uhr, Wetter, Musik, Browser, Timer, Wecker, Zufall, Bello und Notizen. Frag einfach!",
        "danke": "Gern geschehen!",
        "gute nacht": "Gute Nacht! Ich aktiviere den Nachtmodus.",
        "guten morgen": "Guten Morgen! Ich hoffe, du hast gut geschlafen.",
    }

    def __init__(self, app):
        self.app = app
        self.pending_intent = None
        self.pending_until = 0

    def parse(self, raw):
        text = self._normalize(raw)
        if not text:
            return
        # Wake-word entfernen, auch wenn es versehentlich doppelt gesagt wurde
        changed = True
        while changed:
            changed = False
            for w in ("alexa", "computer", "hey"):
                if text.startswith(w):
                    text = text[len(w):].strip(" ,")
                    changed = True
        app = self.app

        if not text:
            app.show_alexa_bar("Ich hoere zu...", 5)
            app.set_status("Ich hoere zu...", 5)
            app.listen_for_followup()
            return

        if self._is_stop_command(text) and app.alert_active():
            was_alarm = app.alarm_ringing
            app.stop_alerts()
            app.go("alarm" if was_alarm else "timer")
            self.pending_intent = None
            return app.respond("Okay, gestoppt.")

        if self.pending_intent and time.time() <= self.pending_until:
            handled = self._handle_pending(text)
            if handled:
                return
        elif self.pending_intent:
            self.pending_intent = None

        # --- Rechnen ---
        math_trigger = (
            re.search(r"\b(rechne|berechne)\b", text)
            or re.search(r"(was|wie ?viel) (ist|sind|macht|ergibt|gibt)", text)
            or "wurzel" in text
            or re.search(r"\d\s*(plus|minus|mal|geteilt|durch|hoch|modulo|\+|\-|\*|/|x)\s*\d", text)
        )
        if math_trigger:
            res = self._try_calc(text)
            if res is not None:
                return app.respond(f"Das ergibt {res}.")

        # --- Navigation / Ansichten ---
        if any(k in text for k in ("wie spaet", "uhrzeit", "wie viel uhr", "zeig die uhr", "uhr")):
            if "wecker" not in text and "timer" not in text:
                now = dt.datetime.now()
                app.go("clock")
                if now.minute == 0:
                    spoken = f"Es ist {now.hour} Uhr."
                else:
                    spoken = f"Es ist {now.hour} Uhr {now.minute}."
                return app.respond(spoken)
        if self._is_weather_question(text):
            app.go("weather")
            return app.respond(self._weather_answer(text))
        # --- Standort: "wo bin ich" / "meine adresse" ---
        if any(k in text for k in (
                "wo bin ich", "wo sind wir", "wo befinde ich", "mein standort",
                "meinen standort", "meine adresse", "welche adresse", "welcher ort",
                "an welchem ort", "wo stehe ich")):
            app.set_status("Bestimme Standort...", 4)
            addr = app.weather.current_address()
            if addr:
                return app.respond(f"Du bist hier: {addr}.")
            return app.respond("Ich konnte deinen Standort gerade nicht bestimmen.")
        if "nachtmodus" in text or "dunkler" in text or "gute nacht" in text:
            app.theme.night = True
            app.rebuild_all()
            app.go("clock")
            return app.respond("Nachtmodus aktiviert.")
        if "tagmodus" in text or "heller" in text or "tag modus" in text:
            app.theme.night = False
            app.rebuild_all()
            return app.respond("Tagmodus aktiviert.")
        if "vollbild" in text:
            app.toggle_fullscreen()
            return app.respond("Vollbild umgeschaltet.")
        if "startbildschirm" in text or "home" in text or "zurueck zum start" in text:
            app.go("home")
            return app.respond("Zurueck zum Startbildschirm.")
        if "einstellung" in text or "settings" in text:
            app.go("settings")
            return app.respond("Hier sind die Einstellungen.")
        if "notiz" in text:
            # "notiz <text>"
            m = re.search(r"notiz[e]?\s+(.*)", text)
            if m and m.group(1).strip():
                app.notes.append(raw.split("notiz", 1)[-1].strip(" :,"))
                app.go("notes")
                return app.respond("Notiz gespeichert.")
            app.go("notes")
            return app.respond("Was soll ich notieren?")

        # --- Bello / Wuff ---
        if ("bello" in text or "wuff" in text or "wau" in text
                or "bellen" in text or "bell mal" in text):
            app.bello()
            return


        # --- Musik ---
        if ("pause" in text and "musik" in text) or text in ("pause", "pausiere"):
            app.music.pause(); app.go("music")
            return app.respond("Musik pausiert.")
        if self._is_stop_command(text) and not any(k in text for k in ("timer", "wecker", "alarm")):
            app.music.stop(); app.go("music")
            return app.respond("Musik gestoppt.")
        if "naechst" in text or "weiter" in text or "skip" in text:
            app.music.next(); app.go("music")
            return app.respond("Naechster Titel.")
        if "vorherig" in text or "zurueck" in text and "musik" in text:
            app.music.prev(); app.go("music")
            return app.respond("Vorheriger Titel.")
        if "leiser" in text:
            app.change_volume(-10)
            return app.respond(f"Lautstaerke {app.music.volume} Prozent.")
        if "lauter" in text:
            app.change_volume(10)
            return app.respond(f"Lautstaerke {app.music.volume} Prozent.")
        # gezielt einen Titel spielen: "spiele <Titel> von <Interpret>"
        m = re.search(r"(?:spiele|spiel|spielen|play|abspielen|hoeren?)\s+(.+)", text)
        if m:
            query = m.group(1).strip()
            # Fuellwoerter am Anfang entfernen
            for fw in ("das lied", "den song", "den titel", "die musik",
                       "das lied von", "lied", "song", "titel", "mir", "bitte"):
                if query.startswith(fw + " "):
                    query = query[len(fw) + 1:]
            query = query.strip()
            # "songs/lieder/musik von <Kuenstler>" -> ganzen Kuenstler spielen
            am = re.match(r"(?:alle\s+|ein paar\s+|paar\s+)?"
                          r"(?:songs|lieder|musik|tracks|playlist|hits|titel)\s+von\s+(.+)",
                          query)
            if am:
                artist = am.group(1).strip()
                app.go("music")
                ok, info = app.music.play_artist(artist)
                return app.respond(f"Ich spiele Songs von {info}." if ok else info)
            if query and query not in ("musik", "music", "etwas", "was", "lied", "song"):
                app.go("music")
                ok, info = app.music.play_query(query)
                return app.respond(f"Ich spiele {info}." if ok else info)

        if "musik" in text or "spiele" in text or "play" in text or "song" in text:
            app.music.play(); app.go("music")
            return app.respond("Ich spiele Musik.")

        # --- Browser ---
        if "youtube" in text and any(k in text for k in ("schliessen", "zumachen", "beenden", "weg", "home")):
            app.close_youtube_home()
            return app.respond("YouTube geschlossen.")
        if "youtube" in text:
            return app.open_youtube()
        if "google maps" in text or "maps" in text or "karte" in text:
            app.open_url("https://maps.google.com", "Maps"); app.go("browser")
            return app.respond("Oeffne Maps.")
        if "uebersetz" in text or "translate" in text:
            app.open_url("https://translate.google.com", "Uebersetzer"); app.go("browser")
            return app.respond("Oeffne den Uebersetzer.")
        if "nachrichten" in text or "news" in text:
            app.open_url("https://news.google.com", "Nachrichten"); app.go("browser")
            return app.respond("Hier sind die Nachrichten.")
        if "google" in text:
            app.open_url("https://google.com", "Google"); app.go("browser")
            return app.respond("Oeffne Google.")
        if "browser" in text or "internet" in text:
            app.go("browser")
            return app.respond("Hier ist der Browser.")

        # --- Timer ---
        if self._is_timer_request(text):
            if self._is_stop_command(text) or "aus" in text or "abbrechen" in text:
                app.timer_stop(); app.go("timer")
                return app.respond("Timer gestoppt.")
            seconds = self._extract_duration_seconds(text)
            if seconds:
                app.timer_set(seconds)
                app.go("timer")
                return app.respond(f"Timer auf {self._human_duration(seconds)} gestellt.")
            app.go("timer")
            return app.ask_followup("timer", "Wie lange soll der Timer laufen?")

        # --- Wecker ---
        if "wecker" in text or "alarm" in text:
            if "aus" in text or "loesch" in text or self._is_stop_command(text):
                app.alarm_off(); app.go("alarm")
                return app.respond("Wecker deaktiviert.")
            tm = self._extract_alarm_target(text, allow_bare_hour=True)
            if tm:
                app.set_alarm_str(tm); app.go("alarm")
                return app.respond(f"Wecker auf {tm} gestellt.")
            app.go("alarm")
            return app.ask_followup("alarm", "Um wie viel Uhr oder in wie vielen Minuten soll ich dich wecken?")

        # --- Witz / Smalltalk ---
        if "witz" in text:
            return app.respond(random.choice(self.JOKES))
        for key, ans in self.SMALLTALK.items():
            if key in text:
                if "gute nacht" in key:
                    app.theme.night = True; app.rebuild_all()
                return app.respond(ans)

        general = self._general_question_answer(text, raw)
        if general:
            return app.respond(general)

        # Zufall: Muenze, Wuerfel, Zufallszahl, Entscheidung
        rnd = self._random_answer(text)
        if rnd:
            return app.respond(rnd)

        # --- nichts erkannt ---
        return app.respond("Das habe ich noch nicht verstanden. Frag mich zum Beispiel nach Wetter, Timer, Wecker, Zufall oder Musik.", understood=False)

    def _try_calc(self, text):
        """Wertet einfache Rechenausdrücke aus. Liefert String oder None."""
        import math as _math
        t = " " + text + " "
        # Wurzel zuerst
        if "wurzel" in t:
            mw = re.search(r"wurzel\s+(?:aus\s+|von\s+)?(-?\d+(?:[.,]\d+)?)", t)
            if mw:
                try:
                    return self._fmt_num(_math.sqrt(float(mw.group(1).replace(",", "."))))
                except Exception:
                    return None
        # deutsche Zahlwoerter -> Ziffern
        numwords = {
            "null": "0", "eins": "1", "ein": "1", "eine": "1", "zwei": "2", "drei": "3",
            "vier": "4", "fuenf": "5", "fünf": "5", "sechs": "6", "sieben": "7",
            "acht": "8", "neun": "9", "zehn": "10", "elf": "11", "zwoelf": "12",
            "zwölf": "12", "zwanzig": "20", "dreissig": "30", "dreißig": "30",
            "vierzig": "40", "fuenfzig": "50", "fünfzig": "50", "hundert": "100",
        }
        for w, n in numwords.items():
            t = re.sub(rf"\b{w}\b", n, t)
        # Operatorwoerter -> Symbole
        for pat, sym in [
            (r"\bmultipliziert mit\b", "*"), (r"\bmal\b", "*"), (r"\bx\b", "*"),
            (r"\bgeteilt durch\b", "/"), (r"\bdurch\b", "/"),
            (r"\bplus\b", "+"), (r"\bminus\b", "-"),
            (r"\bhoch\b", "**"), (r"\bmodulo\b", "%"),
        ]:
            t = re.sub(pat, sym, t)
        # nur Mathe-Zeichen behalten
        expr = "".join(re.findall(r"[0-9+\-*/%.,() ]", t)).strip()
        expr = expr.replace(",", ".")
        if not re.search(r"\d", expr) or not re.search(r"[+\-*/%]", expr):
            return None
        try:
            tree = _ast.parse(expr, mode="eval")
            return self._fmt_num(_safe_eval(tree.body))
        except Exception:
            return None

    def _fmt_num(self, val):
        if isinstance(val, float) and val.is_integer():
            val = int(val)
        elif isinstance(val, float):
            val = round(val, 4)
        return str(val).replace(".", ",")

    def _normalize(self, raw):
        text = raw.strip().lower()
        repl = {
            "ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
            "morgen früh": "morgen frueh", "morges": "morgen",
            "mitwoch": "mittwoch", "strum": "sturm",
        }
        for a, b in repl.items():
            text = text.replace(a, b)
        return text

    def _random_answer(self, text):
        """Muenze, Wuerfel, Zufallszahl, einfache Entscheidung. None wenn nichts passt."""
        import random as _r
        app = self.app

        if any(k in text for k in ("muenze", "kopf oder zahl", "muenz")):
            result = _r.choice(["Kopf", "Zahl"])
            app.start_coin_flip(result=result)
            return f"Die Muenze zeigt {result}."

        if re.search(r"\b(wuerf|wuerfle|wuerfel)", text):
            m = re.search(r"(\d+)\s*seiten", text)
            sides = max(2, min(1000, int(m.group(1)))) if m else 6
            value = _r.randint(1, sides)
            app.start_number_roll(1, sides, result=value)
            return f"Ich wuerfle eine {value} von {sides}."

        # Beispiele: "sage eine Zahl von 1 bis 5", "Zahl von 1-5", "zwischen 1 und 5"
        mr = (re.search(r"zwischen\s+(\d+)\s+und\s+(\d+)", text)
              or re.search(r"(?:zahl|nummer)\s+von\s+(\d+)\s*(?:bis|-|und)\s*(\d+)", text)
              or re.search(r"von\s+(\d+)\s*(?:bis|-)\s*(\d+)", text))
        wants_number = ("zufallszahl" in text or "zufalls zahl" in text
                        or ("zahl" in text and any(k in text for k in ("sag", "sage", "nenn", "nenne", "waehl", "waehle", "von", "zwischen"))))
        if wants_number:
            if mr:
                a, b = int(mr.group(1)), int(mr.group(2))
                lo, hi = min(a, b), max(a, b)
            else:
                lo, hi = 1, 100
            lo, hi = max(-9999, lo), min(9999, hi)
            value = _r.randint(lo, hi)
            app.start_number_roll(lo, hi, result=value)
            return f"Deine Zahl ist {value}."

        md = re.search(r"(?:soll ich|entscheide|was ist besser|nimm)\s+(.+?)\s+oder\s+(.+)", text)
        if md:
            a = md.group(1).strip(" ?.,")
            b = md.group(2).strip(" ?.,")
            if 0 < len(a) < 40 and 0 < len(b) < 40:
                choice = _r.choice([a, b])
                return f"Ich wuerde sagen: {choice}."
        return None

    def _is_stop_command(self, text):
        return bool(re.search(r"\b(stop|stopp|stoppen|halt|ruhe|aus)\b", text))

    def _is_timer_request(self, text):
        return ("timer" in text or text in ("time", "timer")
                or re.search(r"\b(time|timer)\b", text) is not None)

    def _handle_pending(self, text):
        app = self.app
        if self._is_stop_command(text):
            self.pending_intent = None
            app.respond("Okay, abgebrochen.")
            return True
        if self.pending_intent == "timer":
            seconds = self._extract_duration_seconds(text, allow_bare_number=True)
            if seconds:
                self.pending_intent = None
                app.timer_set(seconds)
                app.go("timer")
                app.respond(f"Timer auf {self._human_duration(seconds)} gestellt.")
                return True
            self.pending_until = time.time() + 20
            app.ask_followup("timer", "Sag zum Beispiel zehn Minuten oder 1 Stunde.")
            return True
        if self.pending_intent == "alarm":
            tm = self._extract_alarm_target(text, allow_bare_hour=True)
            if tm:
                self.pending_intent = None
                app.set_alarm_str(tm)
                app.go("alarm")
                app.respond(f"Wecker auf {tm} gestellt.")
                return True
            self.pending_until = time.time() + 20
            app.ask_followup("alarm", "Sag zum Beispiel 7 Uhr, 10.00 oder in 10 Minuten.")
            return True
        return False

    def _extract_duration_seconds(self, text, allow_bare_number=False):
        t = text.replace(",", ".")
        number = r"(\d+(?:\.\d+)?)"
        total = 0.0
        found = False
        for m in re.finditer(number + r"\s*(stunden?|std|h)\b", t):
            total += float(m.group(1)) * 3600
            found = True
        for m in re.finditer(number + r"\s*(minuten?|mins?|m)\b", t):
            total += float(m.group(1)) * 60
            found = True
        for m in re.finditer(number + r"\s*(sekunden?|seks?|s)\b", t):
            total += float(m.group(1))
            found = True
        if found:
            return max(1, int(total))

        m = re.search(r"\b(\d{1,2})[:](\d{2})\b", t)
        if m:
            return int(m.group(1)) * 60 + int(m.group(2))

        if allow_bare_number or self._is_timer_request(t):
            m = re.search(number, t)
            if m:
                return max(1, int(float(m.group(1)) * 60))
        return None

    def _extract_alarm_target(self, text, allow_bare_hour=False):
        # "weck mich in 10 Minuten" -> Uhrzeit relativ zu jetzt
        if re.search(r"\b(in|nach)\b", text) or re.search(r"\b(minuten?|stunden?|sekunden?)\b", text):
            seconds = self._extract_duration_seconds(text)
            if seconds:
                target = dt.datetime.now() + dt.timedelta(seconds=seconds)
                return target.strftime("%H:%M")

        m = re.search(r"\b(\d{1,2})[.:,](\d{2})\b", text)
        if m:
            h, minute = int(m.group(1)), int(m.group(2))
            if 0 <= h <= 23 and 0 <= minute <= 59:
                return f"{h:02d}:{minute:02d}"
        m = re.search(r"\b(\d{1,2})\s*uhr(?:\s*(\d{1,2}))?\b", text)
        if m:
            h = int(m.group(1))
            minute = int(m.group(2) or 0)
            if 0 <= h <= 23 and 0 <= minute <= 59:
                return f"{h:02d}:{minute:02d}"
        if allow_bare_hour:
            m = re.search(r"^\s*(\d{1,2})\s*$", text)
            if m and 0 <= int(m.group(1)) <= 23:
                return f"{int(m.group(1)):02d}:00"
        return None

    def _human_duration(self, seconds):
        seconds = int(seconds)
        if seconds % 3600 == 0:
            h = seconds // 3600
            return f"{h} Stunde" + ("" if h == 1 else "n")
        if seconds % 60 == 0:
            m = seconds // 60
            return f"{m} Minute" + ("" if m == 1 else "n")
        m, s = divmod(seconds, 60)
        if m:
            return f"{m} Minuten und {s} Sekunden"
        return f"{s} Sekunden"

    def _is_weather_question(self, text):
        keys = ("wetter", "regen", "regnet", "regnen", "schnee", "grad",
                "temperatur", "warm", "kalt", "wind", "sturm", "gewitter",
                "sonne", "sonnig", "scheint", "scheinen", "hell",
                "sonnenaufgang", "sonnenuntergang", "uv",
                "bewoelkt", "wolke", "wolken", "aufklar", "klar")
        return any(k in text for k in keys)

    def _weather_answer(self, text):
        wd = self.app.weather.get()
        if not wd:
            return "Ich lade gerade die Wetterdaten."
        idx = self._target_day_index(text, wd)
        if any(k in text for k in ("sonne", "sonnig", "scheint", "scheinen", "hell",
                                    "sonnenaufgang", "sonnenuntergang", "uv", "aufklar", "klar")):
            return self._sun_answer(text, wd, idx)
        if any(k in text for k in ("bewoelkt", "wolke", "wolken")):
            return self._cloud_answer(text, wd, idx)
        if any(k in text for k in ("regen", "regnet", "regnen", "nass")):
            return self._rain_answer(text, wd, idx)
        if any(k in text for k in ("sturm", "gewitter", "boee", "boeen")):
            return self._storm_answer(text, wd, idx)
        if any(k in text for k in ("grad", "temperatur", "warm", "kalt")):
            return self._temperature_answer(text, wd, idx)
        if idx is not None:
            return self._day_weather_answer(text, wd, idx)
        desc = WMO.get(wd["code"], ("Wetter", ""))[0]
        self._set_weather_focus(wd, 0, "Jetzt", "Gerade")
        return (f"In {wd['city']} sind es gerade {wd['temp']} Grad, gefuehlt {wd['feels']} Grad, "
                f"{desc}. Wind {wd['wind']} Kilometer pro Stunde.")

    def _day_weather_answer(self, text, wd, idx):
        idx = self._clamp_day_index(wd, idx)
        fc = wd.get("forecast", [])
        day = fc[idx]
        day_name = self._day_label_for_text(text, idx, day)
        desc, kind = WMO.get(day["code"], ("Wetter", "cloud"))
        hours = self._hours_for_day(wd, idx)
        rain_hours = self._rain_hours(hours)
        storm_hours = self._storm_hours(hours)
        self._set_weather_focus(wd, idx, "Wetter", day_name)
        rain_bits = ""
        if rain_hours:
            total = self._total_precip(rain_hours)
            rain_bits = f" Regen: etwa {total:.1f} Millimeter, maximal {self._max_prob(rain_hours)} Prozent."
        elif day.get("precip_prob", 0):
            rain_bits = f" Regenchance maximal {day.get('precip_prob', 0)} Prozent."
        storm_bits = ""
        if storm_hours:
            gust = self._max_gust(storm_hours)
            storm_bits = f" Achtung, Gewitter oder starke Boeen sind moeglich, Spitzenboeen etwa {gust} Kilometer pro Stunde."
        elif day.get("gust", 0) >= 65:
            storm_bits = f" Es kann stuermisch werden, Boeen bis etwa {day.get('gust')} Kilometer pro Stunde."
        sun_bits = self._sun_summary_sentence(hours, day)
        return (f"{day_name.capitalize()} wird es in {wd['city']} {self._weather_desc_sentence(desc)}, "
                f"mit etwa {day['tmin']} bis {day['tmax']} Grad.{sun_bits}{rain_bits}{storm_bits}")

    def _temperature_answer(self, text, wd, idx=None):
        fc = wd.get("forecast", [])
        idx = 0 if idx is None else self._clamp_day_index(wd, idx)
        day = fc[idx]
        day_name = self._day_label_for_text(text, idx, day)
        morning = any(k in text for k in ("frueh", "morgens", "vormittag"))
        hours = self._hours_for_day(wd, idx)
        self._set_weather_focus(wd, idx, "Temperatur", day_name)
        if morning and hours:
            mh = [h for h in hours if 6 <= h["time"].hour <= 11 and h.get("temp") is not None]
            if mh:
                lo = min(h["temp"] for h in mh)
                hi = max(h["temp"] for h in mh)
                return f"{day_name.capitalize()} frueh liegen die Temperaturen etwa zwischen {lo} und {hi} Grad."
        if idx == 0 and "jetzt" in text:
            return f"Gerade sind es in {wd['city']} {wd['temp']} Grad, gefuehlt {wd['feels']} Grad."
        return f"{day_name.capitalize()} werden es in {wd['city']} etwa {day['tmin']} bis {day['tmax']} Grad."

    def _sun_answer(self, text, wd, idx=None):
        fc = wd.get("forecast", [])
        if not fc:
            return "Ich lade gerade die Sonnendaten."
        if idx is None and any(k in text for k in ("sonnenaufgang", "sonnenuntergang", "uv")):
            idx = 0
        if idx is not None:
            idx = self._clamp_day_index(wd, idx)
            day = fc[idx]
            day_name = self._day_label_for_text(text, idx, day)
            self._set_weather_focus(wd, idx, "Sonne", day_name)
            if "sonnenaufgang" in text:
                return f"{day_name.capitalize()} geht die Sonne um {self._fmt_time(day.get('sunrise'))} Uhr auf."
            if "sonnenuntergang" in text:
                return f"{day_name.capitalize()} geht die Sonne um {self._fmt_time(day.get('sunset'))} Uhr unter."
            if "uv" in text:
                uv = day.get("uv", 0)
                uv_word = "niedrig" if uv < 3 else ("mittel" if uv < 6 else ("hoch" if uv < 8 else "sehr hoch"))
                return f"{day_name.capitalize()} liegt der UV-Index bei etwa {uv}, also {uv_word}."
            hours = self._hours_for_day(wd, idx)
            sun_hours = self._sun_hours(hours)
            windows = self._sun_windows(sun_hours)
            if windows:
                primary = windows[0]
                extra = f", dazu etwa {day.get('sunshine_hours', 0)} Sonnenstunden"
                cloud = self._avg_cloud(sun_hours)
                cloud_bits = f" und nur etwa {cloud} Prozent Wolken in den Sonnenfenstern" if cloud is not None else ""
                return (f"{day_name.capitalize()} kommt die Sonne am ehesten zwischen {primary['start']} und {primary['end']} Uhr raus"
                        f"{extra}{cloud_bits}. Sonnenaufgang {self._fmt_time(day.get('sunrise'))} Uhr, "
                        f"Sonnenuntergang {self._fmt_time(day.get('sunset'))} Uhr.")
            best = self._brightest_hour(hours)
            if best:
                cloud = best.get("cloud")
                cloud_text = f" mit etwa {cloud} Prozent Wolken" if cloud is not None else ""
                return (f"{day_name.capitalize()} sehe ich kein klares Sonnenfenster. Am hellsten wirkt es gegen "
                        f"{best['time'].hour} Uhr{cloud_text}; insgesamt etwa {day.get('sunshine_hours', 0)} Sonnenstunden.")
            return f"{day_name.capitalize()} habe ich noch keine brauchbaren Sonnenstunden-Daten."

        now = dt.datetime.now()
        future = [h for h in wd.get("hourly", []) if h["time"] >= now]
        sun_hours = self._sun_hours(future)
        if sun_hours:
            first = self._sun_windows(sun_hours)[0]
            day_idx = max(0, (sun_hours[0]["time"].date() - dt.date.today()).days)
            fc_day = fc[self._clamp_day_index(wd, day_idx)]
            label = self._relative_day_label(fc_day["date"])
            self._set_weather_focus(wd, day_idx, "Sonne", self._weather_title(day_idx, fc_day))
            return (f"Die naechste Sonne kommt {label} etwa zwischen {first['start']} und {first['end']} Uhr raus. "
                    f"In dem Fenster sind die Wolken am niedrigsten und die Regenchance bleibt gering.")
        self._set_weather_focus(wd, 0, "Sonne", "Sonnenlage")
        return "In den naechsten Tagen sehe ich kaum klare Sonnenfenster. Es bleibt eher wolkig oder wechselhaft."

    def _cloud_answer(self, text, wd, idx=None):
        fc = wd.get("forecast", [])
        idx = 0 if idx is None else self._clamp_day_index(wd, idx)
        day = fc[idx]
        day_name = self._day_label_for_text(text, idx, day)
        hours = self._hours_for_day(wd, idx)
        self._set_weather_focus(wd, idx, "Wolken", day_name)
        avg = self._avg_cloud(hours)
        sun_windows = self._sun_windows(self._sun_hours(hours))
        if avg is None:
            return f"{day_name.capitalize()} habe ich noch keine Wolkendaten."
        if sun_windows:
            first = sun_windows[0]
            return (f"{day_name.capitalize()} ist es im Schnitt zu etwa {avg} Prozent bewoelkt, "
                    f"aber die freundlichste Phase ist zwischen {first['start']} und {first['end']} Uhr.")
        return (f"{day_name.capitalize()} bleibt es ziemlich bewoelkt, im Schnitt etwa {avg} Prozent Wolkendecke. "
                f"Ich sehe kein starkes Sonnenfenster.")

    def _rain_answer(self, text, wd, idx=None):
        if idx is not None:
            idx = self._clamp_day_index(wd, idx)
            hours_all = self._hours_for_day(wd, idx)
            hours = self._rain_hours(hours_all)
            day = wd.get("forecast", [])[idx]
            day_name = self._day_label_for_text(text, idx, day)
            self._set_weather_focus(wd, idx, "Regen", day_name)
            if not hours:
                prob = day.get("precip_prob", 0)
                mm = day.get("precip", 0)
                return (f"{day_name.capitalize()} sieht es nach den aktuellen Daten eher trocken aus. "
                        f"Maximal {prob} Prozent Regenwahrscheinlichkeit, etwa {mm:.1f} Millimeter.")
            windows = self._rain_windows(hours)
            first = windows[0]
            total = self._total_precip(hours)
            storm_hours = self._storm_hours(hours_all)
            storm_bits = ""
            if storm_hours:
                storm_bits = f" Achtung: Gewitter oder starke Boeen sind moeglich, bis etwa {self._max_gust(storm_hours)} Kilometer pro Stunde."
            return (f"{day_name.capitalize()} regnet es wahrscheinlich zwischen {first['start']} und {first['end']} Uhr. "
                    f"Insgesamt etwa {total:.1f} Millimeter, Spitzenwahrscheinlichkeit {first['prob']} Prozent.{storm_bits}")

        now = dt.datetime.now()
        future = [h for h in wd.get("hourly", []) if h["time"] >= now]
        hours = self._rain_hours(future)
        if not hours:
            self._set_weather_focus(wd, 0, "Regen", "Naechster Regen")
            return "In den naechsten Tagen sieht es nach den aktuellen Daten ueberwiegend trocken aus."
        # Nicht nur die erste Regen-Stunde ansagen: Die kann z.B. nur 5% haben,
        # waehrend das Regenfenster spaeter auf 93% steigt. Darum wird hier das
        # zusammenhaengende Regenfenster mit seiner Spitzen-Wahrscheinlichkeit genutzt.
        h = hours[0]
        idx = max(0, (h["time"].date() - dt.date.today()).days)
        fc = wd.get("forecast", [])
        title_day = fc[self._clamp_day_index(wd, idx)] if fc else None
        self._set_weather_focus(wd, idx, "Regen", self._day_name(idx, title_day))
        label = self._relative_day_label(h["time"].date())
        same_day_hours = [x for x in hours if x["time"].date() == h["time"].date()]
        windows = self._rain_windows(same_day_hours)
        if windows:
            first = windows[0]
            return (f"Der naechste Regen sieht nach {label} zwischen {first['start']:02d} und {first['end']:02d} Uhr aus, "
                    f"mit bis zu {first.get('prob', 0)} Prozent Wahrscheinlichkeit.")
        return (f"Der naechste Regen sieht nach {label} gegen {h['time'].hour} Uhr aus, "
                f"mit etwa {h.get('precip_prob', 0)} Prozent Wahrscheinlichkeit.")

    def _storm_answer(self, text, wd, idx=None):
        idx = 0 if idx is None else self._clamp_day_index(wd, idx)
        day = wd.get("forecast", [])[idx]
        day_name = self._day_label_for_text(text, idx, day)
        hours = self._hours_for_day(wd, idx)
        storm_hours = self._storm_hours(hours)
        self._set_weather_focus(wd, idx, "Sturm", day_name)
        if not storm_hours and day.get("gust", 0) < 65:
            return f"{day_name.capitalize()} sehe ich aktuell kein klares Sturm-Signal. Die staerksten Boeen liegen bei etwa {day.get('gust', 0)} Kilometer pro Stunde."
        windows = self._rain_windows(storm_hours, storm=True)
        if windows:
            first = windows[0]
            return (f"{day_name.capitalize()} koennen Gewitter oder starke Boeen zwischen {first['start']} und {first['end']} Uhr auftreten. "
                    f"Spitzenboeen etwa {self._max_gust(storm_hours)} Kilometer pro Stunde.")
        return f"{day_name.capitalize()} kann es stuermisch werden, mit Boeen bis etwa {day.get('gust', 0)} Kilometer pro Stunde."

    def _target_day_index(self, text, wd=None):
        if "uebermorgen" in text:
            return 2
        if "morgen" in text:
            return 1
        if "heute" in text or "jetzt" in text:
            return 0
        weekdays = {
            "montag": 0, "dienstag": 1, "mittwoch": 2, "donnerstag": 3,
            "freitag": 4, "samstag": 5, "sonntag": 6,
        }
        today = dt.date.today()
        for word, weekday in weekdays.items():
            if re.search(rf"\b{word}\b", text):
                delta = (weekday - today.weekday()) % 7
                return delta
        return None

    def _clamp_day_index(self, wd, idx):
        fc = wd.get("forecast", [])
        if not fc:
            return 0
        return max(0, min(int(idx), len(fc) - 1))

    def _day_name(self, idx, day=None):
        if idx == 0:
            return "heute"
        if idx == 1:
            return "morgen"
        if idx == 2:
            return "uebermorgen"
        if day and day.get("day_full"):
            return day["day_full"]
        return f"in {idx} Tagen"

    def _mentions_weekday(self, text):
        return any(re.search(rf"\b{w}\b", text) for w in (
            "montag", "dienstag", "mittwoch", "donnerstag",
            "freitag", "samstag", "sonntag",
        ))

    def _day_label_for_text(self, text, idx, day=None):
        if self._mentions_weekday(text) and day and day.get("day_full"):
            return day["day_full"]
        return self._day_name(idx, day)

    def _weather_title(self, idx, day=None):
        if idx == 0:
            return "Heute"
        if idx == 1:
            return "Morgen"
        if idx == 2:
            return "Uebermorgen"
        if day and day.get("day_full"):
            return day["day_full"]
        return f"In {idx} Tagen"

    def _weather_desc_sentence(self, desc):
        if not desc:
            return "wechselhaft"
        return desc[0].lower() + desc[1:]

    def _relative_day_label(self, date_):
        today = dt.date.today()
        delta = (date_ - today).days
        if delta == 0:
            return "heute"
        if delta == 1:
            return "morgen"
        if delta == 2:
            return "uebermorgen"
        return date_.strftime("%d.%m.")

    def _hours_for_day(self, wd, idx):
        fc = wd.get("forecast", [])
        if idx < len(fc):
            date_ = fc[idx].get("date")
        else:
            date_ = dt.date.today() + dt.timedelta(days=idx)
        return [h for h in wd.get("hourly", []) if h["time"].date() == date_]

    def _rain_hours(self, hours):
        rainy = []
        for h in hours:
            kind = WMO.get(h.get("code"), ("", ""))[1]
            if kind in ("rain", "storm", "snow") or h.get("precip", 0) > 0.05 or h.get("precip_prob", 0) >= 40:
                rainy.append(h)
        return rainy

    def _storm_hours(self, hours):
        stormy = []
        for h in hours:
            kind = WMO.get(h.get("code"), ("", ""))[1]
            if kind == "storm" or h.get("gust", 0) >= 65:
                stormy.append(h)
        return stormy

    def _sun_hours(self, hours):
        sunny = []
        for h in hours:
            hour = h["time"].hour
            if hour < 6 or hour > 21:
                continue
            kind = WMO.get(h.get("code"), ("", ""))[1]
            cloud = h.get("cloud")
            cloud_ok = cloud is None or cloud <= 68
            rain_ok = h.get("precip", 0) <= 0.05 and h.get("precip_prob", 0) <= 45
            if kind in ("sun", "partly") and cloud_ok and rain_ok:
                sunny.append(h)
        return sunny

    def _sun_windows(self, hours):
        return self._rain_windows(hours)

    def _brightest_hour(self, hours):
        candidates = [h for h in hours if 6 <= h["time"].hour <= 21]
        if not candidates:
            return None
        def score(h):
            kind = WMO.get(h.get("code"), ("", ""))[1]
            kind_penalty = {"sun": 0, "partly": 20, "cloud": 45, "fog": 55,
                            "rain": 80, "storm": 100, "snow": 90}.get(kind, 50)
            cloud = h.get("cloud")
            cloud_score = 50 if cloud is None else cloud
            return cloud_score + kind_penalty + h.get("precip_prob", 0) * 0.4
        return min(candidates, key=score)

    def _avg_cloud(self, hours):
        vals = [h.get("cloud") for h in hours if h.get("cloud") is not None]
        if not vals:
            return None
        return round(sum(vals) / len(vals))

    def _fmt_time(self, value):
        if not value:
            return "--:--"
        if isinstance(value, dt.datetime):
            return value.strftime("%H:%M")
        return str(value)[11:16] if len(str(value)) >= 16 else str(value)

    def _sun_summary_sentence(self, hours, day):
        windows = self._sun_windows(self._sun_hours(hours))
        sunshine = day.get("sunshine_hours", 0)
        if windows:
            first = windows[0]
            return f" Sonne am ehesten {first['start']} bis {first['end']} Uhr, etwa {sunshine} Sonnenstunden."
        if sunshine:
            return f" Nur kurze Auflockerungen, etwa {sunshine} Sonnenstunden."
        return ""

    def _hour_window(self, hours):
        start = hours[0]["time"].hour
        end = start + 1
        max_prob = max(h.get("precip_prob", 0) for h in hours)
        prev = start
        for h in hours[1:]:
            if h["time"].hour == prev + 1:
                end = h["time"].hour + 1
                prev = h["time"].hour
            else:
                break
        return start, end, max_prob

    def _rain_windows(self, hours, storm=False):
        if not hours:
            return []
        ordered = sorted(hours, key=lambda h: h["time"])
        groups = []
        cur = [ordered[0]]
        for h in ordered[1:]:
            if h["time"] <= cur[-1]["time"] + dt.timedelta(hours=1):
                cur.append(h)
            else:
                groups.append(cur)
                cur = [h]
        groups.append(cur)
        windows = []
        for group in groups[:4]:
            start = group[0]["time"].hour
            end = group[-1]["time"].hour + 1
            prob = max(h.get("precip_prob", 0) for h in group)
            mm = self._total_precip(group)
            gust = self._max_gust(group)
            windows.append({
                "start": start,
                "end": end,
                "prob": prob,
                "mm": mm,
                "gust": gust,
                "label": f"{start:02d}-{end:02d} Uhr",
                "storm": storm or any(WMO.get(h.get("code"), ("", ""))[1] == "storm" for h in group) or gust >= 65,
            })
        return windows

    def _total_precip(self, hours):
        return round(sum(h.get("precip", 0) or 0 for h in hours), 1)

    def _max_prob(self, hours):
        return max((h.get("precip_prob", 0) for h in hours), default=0)

    def _max_gust(self, hours):
        return max((h.get("gust", 0) for h in hours), default=0)

    def _set_weather_focus(self, wd, idx, mode, title=None):
        fc = wd.get("forecast", [])
        if not fc:
            self.app.weather_focus = None
            return
        idx = self._clamp_day_index(wd, idx)
        day = fc[idx]
        hours = self._hours_for_day(wd, idx)
        rain_hours = self._rain_hours(hours)
        storm_hours = self._storm_hours(hours)
        sun_hours = self._sun_hours(hours)
        desc, kind = WMO.get(day["code"], ("Wetter", "cloud"))
        if storm_hours or kind == "storm" or day.get("gust", 0) >= 65:
            kind = "storm"
        elif rain_hours or kind in ("rain", "snow") or day.get("precip", 0) > 0 or day.get("precip_prob", 0) >= 40:
            kind = "rain"
        elif sun_hours and mode == "Sonne":
            kind = "sun"
        rain_windows = self._rain_windows(rain_hours)
        storm_windows = self._rain_windows(storm_hours, storm=True)
        sun_windows = self._sun_windows(sun_hours)
        self.app.weather_focus = {
            "mode": mode,
            "idx": idx,
            "title": title or self._weather_title(idx, day),
            "desc": desc,
            "kind": kind,
            "tmin": day.get("tmin"),
            "tmax": day.get("tmax"),
            "rain_prob": max(day.get("precip_prob", 0), self._max_prob(rain_hours)),
            "rain_mm": max(day.get("precip", 0), self._total_precip(rain_hours)),
            "rain_windows": rain_windows,
            "storm_windows": storm_windows,
            "sun_windows": sun_windows,
            "sunshine_hours": day.get("sunshine_hours", 0),
            "daylight_hours": day.get("daylight_hours", 0),
            "cloud_avg": self._avg_cloud(hours),
            "sun_cloud_avg": self._avg_cloud(sun_hours),
            "sunrise": self._fmt_time(day.get("sunrise")),
            "sunset": self._fmt_time(day.get("sunset")),
            "uv": day.get("uv", 0),
            "gust": max(day.get("gust", 0), self._max_gust(hours)),
            "wind": day.get("wind", 0),
        }

    def _general_question_answer(self, text, raw):
        now = dt.datetime.now()
        if "datum" in text or "welcher tag" in text or "was ist heute" in text:
            return now.strftime("Heute ist %A, der %d.%m.%Y.")
        if "was kannst du" in text:
            return "Ich kann Wetter, Timer, Wecker, Musik, Zufall, Bello, Notizen und Rechnen."
        # Wikipedia-/Web-Abfrage entfernt: keine ungefragten Lexikon-Antworten mehr.
        return None

# ----------------------------------------------------------------------------
# HAUPT-APP
# ----------------------------------------------------------------------------
class EchoShowApp:
    def __init__(self, config):
        self.config = config
        pygame.init()
        pygame.display.set_caption("Echo Show - Notebook Edition")

        self.fullscreen = config.get("start_fullscreen", False)
        self.windowed_size = (1280, 800)
        self._first_click_patch_names = set()
        self._make_surface()

        self.theme = Theme()
        self.clock = pygame.time.Clock()
        self.running = True
        self.assistant_status = "Bereit"
        self._status_until = 0
        self.last_response = ""
        self._response_until = 0
        self.input_text = ""
        self.input_active = True
        self.notes = []
        self.show_help = False
        self.alexa_bar_until = 0
        self.alexa_bar_text = ""
        self._state_ready = False
        self._last_command_key = ""
        self._last_command_at = 0
        self._followup_listen_until = 0
        self._last_response_text = ""
        self._last_response_at = 0
        self._last_youtube_open = 0
        self.browser_web_rect = None
        self._web_mouse_inside = False
        self.weather_focus = None
        self.random_anim = None

        # Dienste
        self.weather = WeatherService(config.get("weather_city", "Berlin"),
                                      auto=config.get("weather_auto_location", False),
                                      use_gps=config.get("weather_use_gps", False))
        self.music = MusicService(config)
        self.voice = Voice(config.get("tts_voice", ""),
                           config.get("whisper_model", ""),
                           min_volume=config.get("tts_min_volume", 0.30))
        self.voice.set_volume(self.music.volume)
        self.parser = CommandParser(self)
        self.embedded_web = EmbeddedWebView()
        self.spotify_pb = None
        self._spotify_thread()
        self.alert_channel = None
        self.alert_sound = None
        self.alert_kind = None
        self.alert_sound_annoying = None
        self.alert_start = 0.0
        self.alert_escalated = False
        self._caffeinate_proc = None
        self._start_caffeinate()

        # Inaktivitaet / Screensaver
        self.last_activity = time.time()
        self.screensaver = False
        self.hardware_display_sleeping = False
        self.brightness_dimmed = False
        self._brightness_before_standby = None
        self.idle_to_home = 30      # Sekunden -> zurueck zum Home
        self.idle_to_black = int(config.get("standby_after_seconds", 300))
        self.standby_mode = str(config.get("standby_mode", "brightness")).lower().strip()
        # Alter Schalter: falls jemand nur diesen Wert aendert, bleibt es kompatibel.
        self.turn_display_off_in_standby = bool(config.get("turn_display_off_in_standby", False))
        self.wake_brightness = float(config.get("wake_brightness", 0.85))

        # Timer
        self.timer_total = 0
        self.timer_remaining_val = 0
        self.timer_active = False
        self.timer_end = 0
        self._timer_paused_remaining = 0
        self.timer_fired = False

        # Wecker
        self.alarm_time = None
        self.alarm_ringing = False
        self._alarm_last_check = ""
        self._load_state()
        self._state_ready = True

        # Screens
        self.screens = {
            "splash": SplashScreen(self),
            "home": HomeScreen(self),
            "clock": ClockScreen(self),
            "music": MusicScreen(self),
            "browser": BrowserScreen(self),
            "weather": WeatherScreen(self),
            "timer": TimerScreen(self),
            "alarm": AlarmScreen(self),
            "random": RandomScreen(self),
            "notes": NotesScreen(self),
            "settings": SettingsScreen(self),
        }
        self.browser_url = ""
        self.browser_mode = "links"
        self.youtube_section = "Start"
        self.rebuild_all()
        self.current = "splash"
        self.screens["splash"].on_enter()
        self._restore_due_alerts()

        # Wake-Word-Modus automatisch starten (falls aktiviert + Mikrofon da)
        if config.get("voice_wakeword", False):
            ok = self.voice.start_wakeword(self._on_voice_command)
            if ok:
                self.set_status("Hoere auf 'Alexa'", 4)

    # ----- Display -----
    def _make_surface(self):
        flags = pygame.FULLSCREEN if self.fullscreen else pygame.RESIZABLE
        if self.fullscreen:
            info = pygame.display.Info()
            self.screen = pygame.display.set_mode((info.current_w, info.current_h), flags)
        else:
            self.screen = pygame.display.set_mode(self.windowed_size, flags)
        self.width, self.height = self.screen.get_size()
        self._enable_first_click_activation()

    def _enable_first_click_activation(self):
        if _platform.system() != "Darwin":
            return
        try:
            import ctypes
            import objc

            info = pygame.display.get_wm_info()
            handle = info.get("window")
            if handle is None:
                return
            if hasattr(handle, "contentView"):
                nswindow = handle
            else:
                ptr = handle if isinstance(handle, int) else None
                if ptr is None:
                    get_name = ctypes.pythonapi.PyCapsule_GetName
                    get_name.argtypes = [ctypes.py_object]
                    get_name.restype = ctypes.c_char_p
                    get_pointer = ctypes.pythonapi.PyCapsule_GetPointer
                    get_pointer.argtypes = [ctypes.py_object, ctypes.c_char_p]
                    get_pointer.restype = ctypes.c_void_p
                    try:
                        name = get_name(handle)
                    except Exception:
                        name = None
                    ptr = get_pointer(handle, name)
                if not ptr:
                    return
                nswindow = objc.objc_object(c_void_p=ctypes.c_void_p(ptr))

            try:
                nswindow.setAcceptsMouseMovedEvents_(True)
            except Exception:
                pass
            content = nswindow.contentView()
            view_cls = content.__class__
            class_name = getattr(view_cls, "__name__", str(view_cls))
            if class_name in self._first_click_patch_names:
                return
            try:
                class EchoFirstMousePatch(objc.Category(view_cls)):
                    def acceptsFirstMouse_(self, event):
                        return True

                    def acceptsFirstResponder(self):
                        return True
                self._first_click_patch_names.add(class_name)
            except Exception:
                pass
        except Exception:
            pass

    def rebuild_all(self):
        for s in self.screens.values():
            s.build()

    def toggle_fullscreen(self):
        self.fullscreen = not self.fullscreen
        self._make_surface()
        self.rebuild_all()

    def toggle_night(self):
        self.theme.night = not self.theme.night
        self.rebuild_all()
        if self.current == "settings":
            self.screens["settings"].build()

    def toggle_voice(self):
        if self.voice.enabled or HAVE_TTS:
            self.voice.enabled = not self.voice.enabled
        if self.current == "settings":
            self.screens["settings"].build()

    # ----- Persistenz -----
    def _load_state(self):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return

        now = time.time()
        timer = data.get("timer", {})
        self.timer_total = max(0, int(timer.get("total", 0) or 0))
        self.timer_fired = bool(timer.get("fired", False))
        self.timer_active = bool(timer.get("active", False))
        self.timer_end = float(timer.get("end", 0) or 0)
        self.timer_remaining_val = max(0, float(timer.get("remaining", 0) or 0))

        if self.timer_active:
            if self.timer_end <= 0 and self.timer_remaining_val > 0:
                self.timer_end = now + self.timer_remaining_val
            self.timer_remaining_val = max(0, self.timer_end - now)
            if self.timer_remaining_val <= 0:
                self.timer_active = False
                self.timer_fired = True

        alarm = data.get("alarm", {})
        alarm_time = str(alarm.get("time") or "")
        self.alarm_time = alarm_time if re.match(r"^\d{2}:\d{2}$", alarm_time) else None
        self.alarm_ringing = bool(alarm.get("ringing", False) and self.alarm_time)

    def _save_state(self):
        if not getattr(self, "_state_ready", False):
            return
        try:
            timer_remaining = self.timer_remaining()
            data = {
                "version": 1,
                "saved_at": dt.datetime.now().isoformat(timespec="seconds"),
                "timer": {
                    "active": bool(self.timer_active),
                    "fired": bool(self.timer_fired),
                    "total": int(self.timer_total),
                    "remaining": max(0, int(timer_remaining)),
                    "end": float(self.timer_end) if self.timer_active else 0,
                },
                "alarm": {
                    "time": self.alarm_time,
                    "ringing": bool(self.alarm_ringing),
                },
            }
            tmp = STATE_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, STATE_FILE)
        except Exception:
            pass

    def _restore_due_alerts(self):
        if self.timer_fired:
            self.wake()
            self._start_alert("timer")
            self.go("timer")
            self.last_response = "Der Timer ist abgelaufen!"
            self._response_until = time.time() + 6
        if self.alarm_ringing:
            self.wake()
            self._start_alert("alarm")
            self.go("alarm")
            self.last_response = "Dein Wecker klingelt."
            self._response_until = time.time() + 6

    # ----- Standby / Bildschirm dunkel -----
    def _mac_brightness_tool(self):
        """Findet das optionale Homebrew-Tool 'brightness'."""
        for path in ("/opt/homebrew/bin/brightness", "/usr/local/bin/brightness"):
            if os.path.exists(path):
                return path
        try:
            out = _subprocess.run(["which", "brightness"], capture_output=True,
                                  text=True, timeout=1)
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip()
        except Exception:
            pass
        return None

    def _get_macos_brightness(self):
        """Liest die aktuelle Helligkeit, wenn das Tool 'brightness' installiert ist."""
        tool = self._mac_brightness_tool()
        if not tool:
            return None
        try:
            out = _subprocess.run([tool, "-l"], capture_output=True,
                                  text=True, timeout=2)
            import re as _re
            nums = [float(x) for x in _re.findall(r"brightness\s+([0-9.]+)", out.stdout)]
            if nums:
                return max(0.0, min(1.0, nums[0]))
        except Exception:
            pass
        return None

    def _set_macos_brightness(self, value):
        """Setzt die Helligkeit. Beste Methode: brew install brightness."""
        value = max(0.0, min(1.0, float(value)))
        tool = self._mac_brightness_tool()
        if tool:
            try:
                _subprocess.Popen([tool, str(value)], stdout=_subprocess.DEVNULL,
                                  stderr=_subprocess.DEVNULL)
                return True
            except Exception:
                pass

        # Fallback ohne Zusatztool: macOS-Helligkeitstasten simulieren.
        # key code 145 = dunkler, 144 = heller. Braucht manchmal Bedienungshilfen-Recht.
        try:
            key = "145" if value <= 0.01 else "144"
            presses = 20 if value <= 0.01 else max(1, int(round(value * 16)))
            script = '\n'.join([f'tell application "System Events" to key code {key}' for _ in range(presses)])
            _subprocess.Popen(["osascript", "-e", script], stdout=_subprocess.DEVNULL,
                              stderr=_subprocess.DEVNULL)
            return True
        except Exception:
            return False

    def _start_caffeinate(self):
        """Verhindert den System-Schlaf, damit Wecker/Timer auch nachts ausloesen.
        Das Display darf weiter in den Standby (caffeinate -i blockiert nur Idle-Sleep)."""
        if _platform.system() != "Darwin":
            return
        try:
            self._caffeinate_proc = _subprocess.Popen(
                ["caffeinate", "-i", "-s"],
                stdout=_subprocess.DEVNULL, stderr=_subprocess.DEVNULL)
        except Exception:
            self._caffeinate_proc = None

    def _stop_caffeinate(self):
        try:
            if self._caffeinate_proc:
                self._caffeinate_proc.terminate()
        except Exception:
            pass
        self._caffeinate_proc = None

    def _request_display_sleep(self):
        """Aktiviert Standby: bevorzugt Helligkeit 0, damit macOS nicht sperrt."""
        if self.hardware_display_sleeping or self.brightness_dimmed:
            return
        system = _platform.system()
        mode = self.standby_mode

        if system == "Darwin" and mode == "brightness":
            self._brightness_before_standby = self._get_macos_brightness()
            ok = self._set_macos_brightness(0.0)
            self.brightness_dimmed = bool(ok)
            if ok:
                return
            # Falls kein Tool/Recht vorhanden ist, bleibt der schwarze Standby-Screen.

        if (mode == "display_sleep" or self.turn_display_off_in_standby) and mode != "black":
            self.hardware_display_sleeping = True
            try:
                if system == "Darwin":
                    _subprocess.Popen(["pmset", "displaysleepnow"],
                                      stdout=_subprocess.DEVNULL,
                                      stderr=_subprocess.DEVNULL)
                elif system == "Linux":
                    _subprocess.Popen(["xset", "dpms", "force", "off"],
                                      stdout=_subprocess.DEVNULL,
                                      stderr=_subprocess.DEVNULL)
            except Exception:
                pass

    def _request_display_wake(self):
        """Macht den Bildschirm wieder sichtbar, z.B. wenn 'Alexa' erkannt wurde."""
        was_sleeping = self.hardware_display_sleeping
        was_dimmed = self.brightness_dimmed
        self.hardware_display_sleeping = False
        self.brightness_dimmed = False
        system = _platform.system()
        if not was_sleeping and not was_dimmed and not self.screensaver:
            return
        try:
            if system == "Darwin":
                if was_dimmed:
                    target = self._brightness_before_standby
                    if target is None or target < 0.05:
                        target = self.wake_brightness
                    self._set_macos_brightness(target)
                else:
                    _subprocess.Popen(["caffeinate", "-u", "-t", "2"],
                                      stdout=_subprocess.DEVNULL,
                                      stderr=_subprocess.DEVNULL)
            elif system == "Linux":
                _subprocess.Popen(["xset", "dpms", "force", "on"],
                                  stdout=_subprocess.DEVNULL,
                                  stderr=_subprocess.DEVNULL)
        except Exception:
            pass

    # ----- Navigation -----
    def go(self, name):
        if name != "browser":
            self.hide_embedded_web()
        if name in self.screens:
            self.current = name
            self.screens[name].on_enter()

    # ----- Assistent -----
    def respond(self, text, understood=True):
        now = time.time()
        self.last_response = text
        self._response_until = now + 6
        self.set_status("Erledigt" if understood else "Nicht verstanden", 3)
        if text == self._last_response_text and now - self._last_response_at < 2.5:
            return
        self._last_response_text = text
        self._last_response_at = now
        self.voice.say(text)

    def set_status(self, text, duration=2):
        self.assistant_status = text
        self._status_until = time.time() + duration

    def greeting(self):
        h = dt.datetime.now().hour
        if h < 11:
            return "Guten Morgen"
        if h < 18:
            return "Guten Tag"
        return "Guten Abend"

    def submit_command(self, text):
        if self._is_duplicate_command(text):
            return
        self.set_status("Verarbeite...", 1.2)
        self.parser.parse(text)

    def show_alexa_bar(self, text="Ich hoere zu...", duration=4):
        self.alexa_bar_text = text
        self.alexa_bar_until = time.time() + duration

    def ask_followup(self, intent, prompt):
        self.parser.pending_intent = intent
        self.parser.pending_until = time.time() + 20
        self.respond(prompt)
        self.listen_for_followup()

    def listen_for_followup(self):
        if not (HAVE_SR and self.voice.recognizer):
            return
        now = time.time()
        if self._followup_listen_until > now:
            self.show_alexa_bar("Ich hoere zu...", 5)
            return
        self._followup_listen_until = now + 9

        def wait_and_listen():
            deadline = time.time() + 6
            while self.voice.speaking and time.time() < deadline:
                time.sleep(0.05)
            time.sleep(0.25)
            self.show_alexa_bar("Ich hoere zu...", 8)
            self.set_status("Ich warte auf deine Antwort...", 10)
            self.voice.listen_once(self._on_voice)

        threading.Thread(target=wait_and_listen, daemon=True).start()

    def start_listening(self):
        if not HAVE_SR:
            self.respond("Das Mikrofon ist nicht verfuegbar, du kannst tippen.")
            return
        self.show_alexa_bar("Ich hoere zu...", 8)
        self.set_status("Ich hoere zu...", 8)
        self.voice.listen_once(self._on_voice)

    def _on_voice(self, text):
        self._followup_listen_until = 0
        if text:
            self.input_text = text
            self.submit_command(text)
        else:
            self.set_status("Nichts verstanden", 2)

    def _on_voice_command(self, text):
        """Wird vom Wake-Word-Hintergrund-Thread aufgerufen (Satz enthielt 'Alexa')."""
        self.wake()
        self.show_alexa_bar("Alexa", 5)
        if self._is_duplicate_command(text):
            return
        self.set_status("Verarbeite...", 1.2)
        # parse() entfernt das Wake-Word selbst
        self.parser.parse(text)

    def _command_key(self, text):
        key = self.parser._normalize(text)
        changed = True
        while changed:
            changed = False
            for w in ("alexa", "computer", "hey"):
                if key.startswith(w):
                    key = key[len(w):].strip(" ,")
                    changed = True
        key = re.sub(r"\s+", " ", key).strip(" ,.!?")
        return key

    def _is_duplicate_command(self, text, window=3.0):
        key = self._command_key(text)
        if not key:
            return False
        now = time.time()
        if key == self._last_command_key and now - self._last_command_at < window:
            self.show_alexa_bar("Schon gehoert", 1.2)
            return True
        self._last_command_key = key
        self._last_command_at = now
        return False

    def toggle_wakeword(self):
        active = self.voice.toggle_wakeword(self._on_voice_command)
        if active:
            self.set_status("Hoere auf 'Alexa'", 3)
        else:
            self.set_status("Mikrofon aus", 2)
        if self.current == "settings":
            self.screens["settings"].build()
        if not active and not self.voice.listening and not HAVE_SR:
            self.respond("Spracheingabe nicht verfuegbar. Installiere SpeechRecognition und pyaudio.")

    # ----- Browser -----
    def open_url(self, url, name):
        self.browser_mode = "links"
        self.browser_url = url
        self.browser_web_rect = None
        self.hide_embedded_web()
        if "browser" in self.screens:
            self.screens["browser"].build()
        try:
            webbrowser.open(url)
        except Exception:
            self.respond(f"Konnte {name} nicht oeffnen.")

    def open_external_url(self, url):
        try:
            webbrowser.open(url)
        except Exception:
            self.respond("Konnte den Browser nicht oeffnen.")

    def open_youtube(self):
        now = time.time()
        already_open = self.current == "browser" and self.browser_mode == "youtube"
        if already_open and now - self._last_youtube_open < 1.5:
            return
        self._last_youtube_open = now
        self.browser_mode = "youtube"
        self.browser_url = "https://youtube.com"
        if "browser" in self.screens:
            self.screens["browser"].build()
        self.go("browser")
        if not already_open:
            self.respond("YouTube ist im Hauptfenster geoeffnet.")

    def set_youtube_section(self, section):
        self.youtube_section = section
        self.browser_mode = "youtube"
        self.browser_url = f"https://youtube.com/{section.lower()}"
        if "browser" in self.screens:
            self.screens["browser"].build()

    def set_browser_links(self):
        self.browser_mode = "links"
        self.browser_url = ""
        self.browser_web_rect = None
        self.hide_embedded_web()
        if "browser" in self.screens:
            self.screens["browser"].build()

    def show_embedded_web(self, url, rect):
        return self.embedded_web.show(url, rect, self.height)

    def focus_embedded_web(self):
        if hasattr(self, "embedded_web"):
            self.embedded_web.focus()

    def move_embedded_web_mouse(self, pos):
        if hasattr(self, "embedded_web"):
            self.embedded_web.mouse_moved(pos, self.height)

    def hide_embedded_web(self):
        self._web_mouse_inside = False
        if hasattr(self, "embedded_web"):
            self.embedded_web.hide()

    def close_youtube_home(self):
        self.browser_mode = "links"
        self.browser_url = ""
        self.browser_web_rect = None
        self._web_mouse_inside = False
        if hasattr(self, "embedded_web"):
            self.embedded_web.close()
        self.go("home")

    def set_volume(self, value):
        self.music.set_volume(value)
        self.voice.set_volume(self.music.volume)
        if self.current == "settings":
            self.screens["settings"].build()

    def change_volume(self, delta):
        self.set_volume(self.music.volume + delta)

    # ----- Zufall / Bello -----
    def start_coin_flip(self, result=None):
        result = result or random.choice(["Kopf", "Zahl"])
        self.random_anim = {"type": "coin", "result": result, "start": time.time(), "duration": 2.4}
        self.go("random")

    def start_number_roll(self, lo=1, hi=5, result=None):
        lo, hi = int(lo), int(hi)
        lo, hi = min(lo, hi), max(lo, hi)
        result = int(result) if result is not None else random.randint(lo, hi)
        self.random_anim = {"type": "number", "range": (lo, hi), "result": result, "start": time.time(), "duration": 2.4}
        self.go("random")

    def bello(self):
        """Plays dog.mp3 exactly once and does nothing else."""
        self._play_bello_sound_once()

    # ----- Timer-Logik -----
    def timer_set(self, seconds):
        self._stop_alert_sound()
        self.timer_total = seconds
        self.timer_remaining_val = seconds
        self.timer_active = True
        self.timer_fired = False
        self.timer_end = time.time() + seconds
        self._save_state()

    def timer_add(self, minutes):
        add = minutes * 60
        if self.timer_active:
            self.timer_end += add
            self.timer_total += add
            self._save_state()
        else:
            self.timer_set((self.timer_remaining_val or 0) + add)

    def timer_start(self):
        if self.timer_remaining_val > 0:
            self._stop_alert_sound()
            self.timer_active = True
            self.timer_fired = False
            self.timer_end = time.time() + self.timer_remaining_val
            self._save_state()

    def timer_pause(self):
        if self.timer_active:
            self.timer_remaining_val = max(0, self.timer_end - time.time())
            self.timer_active = False
            self._save_state()

    def timer_stop(self):
        self._stop_alert_sound()
        self.timer_active = False
        self.timer_remaining_val = 0
        self.timer_total = 0
        self.timer_fired = False
        self._save_state()

    def timer_remaining(self):
        if self.timer_active:
            self.timer_remaining_val = self.timer_end - time.time()
        return self.timer_remaining_val

    def _check_timer(self):
        if self.timer_active and self.timer_end - time.time() <= 0 and not self.timer_fired:
            self.timer_fired = True
            self.timer_active = False
            self.timer_remaining_val = 0
            self._save_state()
            self.wake()
            self.respond("Der Timer ist abgelaufen!")
            self._start_alert("timer")
            self.go("timer")

    # ----- Wecker-Logik -----
    def set_alarm_str(self, hhmm):
        self._stop_alert_sound()
        self.alarm_time = hhmm
        self.alarm_ringing = False
        self._save_state()

    def alarm_off(self):
        self._stop_alert_sound()
        self.alarm_time = None
        self.alarm_ringing = False
        self._save_state()

    def alarm_dismiss(self):
        self._stop_alert_sound()
        self.alarm_ringing = False
        self._save_state()

    def _check_alarm(self):
        if not self.alarm_time or self.alarm_ringing:
            return
        now = dt.datetime.now().strftime("%H:%M")
        if now == self.alarm_time and self._alarm_last_check != now:
            self.alarm_ringing = True
            self._save_state()
            self.wake()
            self.respond("Guten Morgen! Dein Wecker klingelt.")
            self._start_alert("alarm")
            self.go("alarm")
        self._alarm_last_check = now

    def alert_active(self):
        channel_busy = bool(self.alert_channel and self.alert_channel.get_busy())
        return channel_busy or self.timer_fired or self.alarm_ringing

    def stop_alerts(self):
        if self.timer_fired:
            self.timer_stop()
        if self.alarm_ringing:
            self.alarm_dismiss()
        self._stop_alert_sound()

    def _start_alert(self, kind):
        self.alert_kind = kind
        self.alert_start = time.time()
        self.alert_escalated = False
        try:
            if not self.music.have_mixer:
                return
            if self.alert_sound is None:
                self.alert_sound = self._make_alert_sound()
            self.alert_channel = pygame.mixer.find_channel()
            if self.alert_channel:
                self.alert_channel.play(self.alert_sound, loops=-1)
        except Exception:
            pass

    def _update_alert(self):
        """Nach 1 Minute vom chilligen auf den nervigen Ton eskalieren."""
        if not (self.alert_channel and self.alert_channel.get_busy()):
            return
        if self.alert_escalated:
            return
        if time.time() - self.alert_start >= 60:
            try:
                if self.alert_sound_annoying is None:
                    self.alert_sound_annoying = self._make_annoying_sound()
                self.alert_channel.stop()
                ch = pygame.mixer.find_channel()
                if ch:
                    ch.play(self.alert_sound_annoying, loops=-1)
                    self.alert_channel = ch
                self.alert_escalated = True
            except Exception:
                pass

    def _stop_alert_sound(self):
        try:
            if self.alert_channel:
                self.alert_channel.stop()
        except Exception:
            pass
        self.alert_channel = None
        self.alert_kind = None
        self.alert_escalated = False
        self.alert_start = 0.0

    def _make_alert_sound(self):
        import array
        init = pygame.mixer.get_init() or (44100, -16, 1)
        sr_, _, channels = init
        length = 1.8
        frames = int(sr_ * length)
        buf = array.array("h")
        for i in range(frames):
            t = i / sr_
            edge = min(1.0, i / (sr_ * 0.12), (frames - i) / (sr_ * 0.18))
            tremolo = 0.62 + 0.38 * (math.sin(2 * math.pi * 1.4 * t) + 1) / 2
            tone = (math.sin(2 * math.pi * 523.25 * t)
                    + 0.55 * math.sin(2 * math.pi * 659.25 * t)
                    + 0.25 * math.sin(2 * math.pi * 783.99 * t))
            sample = int(11000 * edge * tremolo * tone / 1.8)
            if channels == 2:
                buf.append(sample)
                buf.append(sample)
            else:
                buf.append(sample)
        return pygame.mixer.Sound(buffer=buf.tobytes())

    def _make_annoying_sound(self):
        """Lauter, harscher Wecker-Ton (schnelle Rechteck-Pieptoene) fuer die Eskalation."""
        import array
        init = pygame.mixer.get_init() or (44100, -16, 1)
        sr_, _, channels = init
        # Muster: pieep-pieep-pieep (hoch), kurze Pause -> wiederholt
        pattern = [(1320, 0.13), (0, 0.05), (1320, 0.13), (0, 0.05),
                   (1660, 0.16), (0, 0.30)]
        buf = array.array("h")
        amp = 24000  # deutlich lauter als der Chill-Ton
        for freq, dur in pattern:
            frames = int(sr_ * dur)
            for i in range(frames):
                if freq <= 0:
                    sample = 0
                else:
                    # Rechteckwelle = harsch/nervig
                    phase = (freq * i / sr_) % 1.0
                    sq = 1.0 if phase < 0.5 else -1.0
                    # leichtes Tremolo fuer extra Penetranz
                    trem = 0.85 + 0.15 * math.sin(2 * math.pi * 8 * i / sr_)
                    sample = int(amp * sq * trem)
                if channels == 2:
                    buf.append(sample)
                    buf.append(sample)
                else:
                    buf.append(sample)
        return pygame.mixer.Sound(buffer=buf.tobytes())

    def _play_bello_sound_once(self):
        """Plays dog.mp3 once if the file sits next to the script."""
        try:
            if not getattr(self.music, "have_mixer", False):
                return
            path = os.path.join(APP_DIR, "dog.mp3")
            if not os.path.isfile(path):
                return
            sound = pygame.mixer.Sound(path)
            sound.play(loops=0)
        except Exception:
            pass

    # ----- Spotify Poll -----
    def _spotify_thread(self):
        def loop():
            while True:
                if self.music.mode == "spotify":
                    self.spotify_pb = self.music.poll_spotify()
                time.sleep(2)
        threading.Thread(target=loop, daemon=True).start()

    # ----- Alexa-Ring zeichnen -----
    def draw_alexa_ring(self, surf, cx, cy, r):
        t = self.theme
        listening = "hoere" in self.assistant_status.lower()
        speed = 4 if listening else 1.5
        pulse = (math.sin(time.time() * speed) + 1) / 2
        # aeusserer Glow
        glow = pygame.Surface((r * 4, r * 4), pygame.SRCALPHA)
        for i in range(6, 0, -1):
            a = int(18 * (pulse if listening else 0.7) * (i / 6))
            col = t.accent if not listening else (90, 200, 255)
            pygame.draw.circle(glow, (*col, a), (r * 2, r * 2), int(r + i * r * 0.12))
        surf.blit(glow, (cx - r * 2, cy - r * 2))
        # Ringe
        pygame.draw.circle(surf, t.accent2, (cx, cy), int(r * (1 + pulse * 0.05)), 4)
        pygame.draw.circle(surf, t.accent, (cx, cy), int(r * 0.78), 6)
        pygame.draw.circle(surf, t.accent, (cx, cy), int(r * 0.3))

    # ----- Eingabeleiste -----
    def draw_input_bar(self, surf):
        t = self.theme
        W, H = self.width, self.height
        bar_h = 56
        bar = pygame.Rect(int(W * 0.05), H - bar_h - 14, int(W * 0.90), bar_h)
        pygame.draw.rect(surf, t.card, bar, border_radius=28)
        pygame.draw.rect(surf, t.accent if self.input_active else t.card_line, bar, 2,
                         border_radius=28)
        prompt = "Befehl eingeben  (z.B. 'Alexa, zeig Wetter')   Enter = senden"
        shown = self.input_text if self.input_text else prompt
        col = t.text if self.input_text else t.muted
        # Cursor blinkt
        cursor = "|" if (self.input_text and int(time.time() * 2) % 2 == 0) else ""
        draw_text(surf, fit_text(shown + cursor, 24, bar.width - 120),
                  24, col, (bar.left + 28, bar.centery), center=False)
        # Mikrofon-Status rechts in der Leiste
        if self.voice.listening:
            blink = int(time.time() * 2) % 2 == 0
            col = t.good if blink else t.muted
            draw_text(surf, "ALEXA", 18, col, (bar.right - 55, bar.centery),
                      center=True, bold=True)
        else:
            mic = "MIC" if HAVE_SR else "TXT"
            draw_text(surf, mic, 18, t.muted, (bar.right - 50, bar.centery), center=True, bold=True)

    # ----- Alexa-Zuhoerleiste -----
    def draw_alexa_bar(self, surf):
        if time.time() > self.alexa_bar_until:
            return
        W, H = self.width, self.height
        now = time.time()
        progress = max(0, min(1, (self.alexa_bar_until - now) / 5.0))
        alpha = int(80 + 150 * min(1, progress * 1.4))

        # Die Zuhoer-Anzeige hatte vorher keine richtige Box und lag zu tief am Rand.
        # Jetzt sitzt Text + Wellenanzeige sauber in einer eigenen abgerundeten Box.
        box_w = int(W * 0.68)
        box_h = 58
        box = pygame.Rect(0, 0, box_w, box_h)
        box.midbottom = (W // 2, H - 22)

        box_surf = pygame.Surface(box.size, pygame.SRCALPHA)
        pulse = (math.sin(now * 5.5) + 1) / 2
        pygame.draw.rect(box_surf, (10, 25, 48, int(205 + pulse * 25)), box_surf.get_rect(), border_radius=22)
        pygame.draw.rect(box_surf, (72, 204, 255, int(170 + pulse * 55)), box_surf.get_rect(), 2, border_radius=22)

        label = self.alexa_bar_text or "Ich hoere zu..."
        draw_text(box_surf, fit_text(label, 17, box_w - 60, bold=True), 17,
                  (190, 240, 255), (box_w // 2, 17), center=True, bold=True, alpha=alpha)

        bar_w = box_w - 70
        bar_h = 16
        x = (box_w - bar_w) // 2
        y = 34

        track = pygame.Rect(x, y, bar_w, bar_h)
        pygame.draw.rect(box_surf, (13, 26, 48), track, border_radius=bar_h // 2)
        pygame.draw.rect(box_surf, (72, 204, 255), track, 2, border_radius=bar_h // 2)

        # Wellen werden absichtlich auf die Spur geclippt, damit nichts aus der Box ragt.
        old_clip = box_surf.get_clip()
        box_surf.set_clip(track.inflate(-4, -4))
        segs = 22
        gap = 5
        seg_w = max(8, (bar_w - gap * (segs + 1)) // segs)
        for i in range(segs):
            phase = now * 4.6 + i * 0.62
            h = int(4 + (math.sin(phase) + 1) * 5)
            sx = x + gap + i * (seg_w + gap)
            sy = y + (bar_h - h) // 2
            col = (30, 181 + int(50 * math.sin(phase) ** 2), 255, alpha)
            s = pygame.Surface((seg_w, h), pygame.SRCALPHA)
            pygame.draw.rect(s, col, s.get_rect(), border_radius=4)
            box_surf.blit(s, (sx, sy))
        box_surf.set_clip(old_clip)

        surf.blit(box_surf, box)

    # ----- Response-Bubble -----
    def draw_response(self, surf):
        if time.time() > self._response_until or not self.last_response:
            return
        t = self.theme
        W, H = self.width, self.height
        txt = self.last_response
        font = get_font(24, True)
        tw = min(font.size(txt)[0] + 50, int(W * 0.7))
        bub = pygame.Rect(0, 0, tw, 58)
        bub.midbottom = (W // 2, H - 84)
        s = pygame.Surface(bub.size, pygame.SRCALPHA)
        pygame.draw.rect(s, (*t.accent, 235), s.get_rect(), border_radius=20)
        surf.blit(s, bub)
        draw_text(surf, fit_text(txt, 24, tw - 40, bold=True), 24, (10, 14, 28),
                  bub.center, center=True, bold=True)

    # ----- Hilfe-Overlay -----
    def draw_help(self, surf):
        t = self.theme
        W, H = self.width, self.height
        ov = pygame.Surface((W, H), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 210))
        surf.blit(ov, (0, 0))
        lines = [
            "TASTEN & SPRACHE",
            "",
            "Sprich einfach: 'Alexa, ...'   (Mic hoert dauerhaft zu)",
            "Hellblaue Leiste unten = Alexa hoert gerade zu",
            "Leertaste = einmal manuell zuhoeren",
            "F11 = Vollbild     Esc = zum Home-Screen",
            "L = Alexa-Sprachmodus an/aus     +/- = Lautstaerke",
            "H Home  U Uhr  M Musik  B Browser  W Wetter",
            "T Timer  A Wecker  S Einstellungen  N Notizen",
            "",
            "Nach 30 s ohne Aktion -> Home, nach 5 min -> schwarz",
            "",
            "SPRACHBEFEHLE:",
            "'Alexa, wie spaet ist es?'   'Alexa, spiele Musik'",
            "'Alexa, zeig Wetter'         'Alexa, YouTube'",
            "'Alexa, wann regnet es?'     'Alexa, wie viel Grad morgen?'",
            "'Alexa, wo bin ich?'         'Alexa, was ist meine Adresse?'",
            "'Alexa, Timer' -> '10 Minuten'  'Alexa, Wecker' -> '10.00'",
            "'Alexa, wirf eine Muenze'  'Alexa, sage eine Zahl von 1 bis 5'",
            "'Alexa, Bello'",
            "'Alexa, Nachtmodus'",
            "'Alexa, erzaehl einen Witz'  'notiz Milch kaufen'",
            "",
            "? oder Esc schliesst diese Hilfe",
        ]
        y = int(H * 0.16)
        for i, ln in enumerate(lines):
            size = 34 if i == 0 else 22
            col = t.accent if (i == 0 or ln.isupper()) else t.text
            draw_text(surf, ln, size, col, (W // 2, y), center=True,
                      bold=(i == 0 or ln.endswith(":")))
            y += 34 if i == 0 else 30

    # ----- Events -----
    def handle_event(self, e):
        if e.type == pygame.QUIT:
            self.running = False
            return
        # Aktivitaet registrieren / aus Screensaver aufwecken
        if e.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP,
                      pygame.MOUSEMOTION, pygame.MOUSEWHEEL):
            waking = self.screensaver or self.hardware_display_sleeping
            if waking:
                self.wake()
                return  # erster Input weckt nur den Bildschirm, fuehrt keine Aktion aus
            self.last_activity = time.time()
        # Klingelnder Wecker/Timer: erster Tastendruck ODER Klick stoppt sofort,
        # egal auf welchem Screen (der laute Ton uebertoent sonst die Sprachsteuerung)
        if e.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN) and self.alert_active():
            self.stop_alerts()
            self.last_activity = time.time()
            return
        if self._event_belongs_to_embedded_web(e):
            return
        if e.type == pygame.VIDEORESIZE and not self.fullscreen:
            self.windowed_size = (e.w, e.h)
            self._make_surface()
            self.rebuild_all()
        elif e.type == pygame.KEYDOWN:
            self._on_key(e)
        self.screens[self.current].handle_event(e)

    def _event_belongs_to_embedded_web(self, e):
        if self.current != "browser" or self.browser_mode != "youtube":
            self._web_mouse_inside = False
            return False
        rect = self.browser_web_rect
        if not rect:
            self._web_mouse_inside = False
            return False
        mouse_events = (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP,
                        pygame.MOUSEMOTION, pygame.MOUSEWHEEL)
        if e.type in mouse_events:
            pos = getattr(e, "pos", None)
            if pos is None:
                pos = pygame.mouse.get_pos()
            if rect.collidepoint(pos):
                if e.type == pygame.MOUSEBUTTONDOWN or not self._web_mouse_inside:
                    self.focus_embedded_web()
                if e.type == pygame.MOUSEMOTION:
                    self.move_embedded_web_mouse(pos)
                self._web_mouse_inside = True
                return True
            self._web_mouse_inside = False
        if e.type == pygame.KEYDOWN and getattr(e, "key", None) != pygame.K_F11:
            return True
        if hasattr(pygame, "TEXTINPUT") and e.type == pygame.TEXTINPUT:
            return True
        return False

    def _on_key(self, e):
        if self.show_help:
            if e.key in (pygame.K_ESCAPE, pygame.K_QUESTION) or e.unicode == "?":
                self.show_help = False
            return

        if e.key == pygame.K_F11:
            self.toggle_fullscreen(); return
        if e.key == pygame.K_ESCAPE:
            # Vollbild bleibt erhalten; Esc geht nur noch zum Home-Screen
            self.go("home"); return
        if e.key == pygame.K_SPACE:
            self.start_listening(); return

        shortcuts = {
            pygame.K_h: "home", pygame.K_u: "clock", pygame.K_m: "music",
            pygame.K_b: "browser", pygame.K_w: "weather", pygame.K_t: "timer",
            pygame.K_a: "alarm", pygame.K_s: "settings",
            pygame.K_n: "notes",
        }
        if e.key in shortcuts:
            self.go(shortcuts[e.key]); return
        if e.key == pygame.K_l:
            self.toggle_wakeword(); return
        if e.unicode == "?":
            self.show_help = True; return
        if e.key in (pygame.K_PLUS, pygame.K_KP_PLUS) or e.unicode == "+":
            self.change_volume(10); return
        if e.key in (pygame.K_MINUS, pygame.K_KP_MINUS) or e.unicode == "-":
            self.change_volume(-10); return

    # ----- Update -----
    def update(self, dt_):
        if time.time() > self._status_until and "hoere" not in self.assistant_status.lower():
            self.assistant_status = "Bereit"
        self.weather.maybe_refresh()
        self._check_timer()
        self._check_alarm()
        self._update_alert()

        # Inaktivitaet auswerten (Splash zaehlt nicht)
        if self.current != "splash":
            idle = time.time() - self.last_activity
            if idle >= self.idle_to_black:
                self.screensaver = True
            elif idle >= self.idle_to_home and self.current != "home":
                self.go("home")

        self.screens[self.current].update(dt_)

    def wake(self):
        """Bildschirm/Timer aufwecken (z.B. wenn Alarm, Timer oder Alexa ausloest)."""
        self._request_display_wake()
        self.last_activity = time.time()
        self.screensaver = False

    # ----- Draw -----
    def draw(self):
        # Standby: einmal schwarz zeichnen, dann Helligkeit auf 0 / Display-Standby anfordern.
        # Danach nicht weiter mit 60 FPS schwarz rendern -> spart Akku/CPU.
        if self.screensaver:
            if not self.hardware_display_sleeping:
                self.screen.fill((0, 0, 0))
                pygame.display.flip()
                self._request_display_sleep()
            return
        t = self.theme
        bg = gradient_surface((self.width, self.height), t.bg_top, t.bg_bottom)
        self.screen.blit(bg, (0, 0))
        self.screens[self.current].draw(self.screen)
        # Antwort-Bubble (Eingabeleiste wurde entfernt -> reine Sprachsteuerung)
        if self.current not in ("splash",):
            self.draw_alexa_bar(self.screen)
            self.draw_response(self.screen)
        if self.show_help:
            self.draw_help(self.screen)
        pygame.display.flip()

    # ----- Loop -----
    def run(self, smoke_frames=None):
        frames = 0
        while self.running:
            fps = 5 if self.screensaver or self.hardware_display_sleeping or self.brightness_dimmed else 60
            dt_ = self.clock.tick(fps) / 1000.0
            for e in pygame.event.get():
                self.handle_event(e)
            self.update(dt_)
            self.draw()
            frames += 1
            if smoke_frames and frames >= smoke_frames:
                self.running = False
        try:
            self.hide_embedded_web()
            if hasattr(self, "embedded_web"):
                self.embedded_web.close()
            self._save_state()
            self.voice.stop_wakeword()
            self._stop_caffeinate()
        except Exception:
            pass
        pygame.quit()


# ----------------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------------
def main():
    smoke = os.environ.get("ECHO_SMOKE")
    if smoke:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    try:
        app = EchoShowApp(CONFIG)
        app.run(smoke_frames=int(smoke) if smoke else None)
    except Exception as ex:
        # Letzte Verteidigungslinie: nicht kommentarlos abstuerzen
        import traceback
        print("Unerwarteter Fehler:")
        traceback.print_exc()
        try:
            pygame.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()