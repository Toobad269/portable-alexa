# Echo Show – Notebook Edition

Turns your laptop into a smart display in the style of an Amazon Echo Show.
A single Python file, started with `python3 echo_show.py`.

> **Note on language:** the on-screen UI and the assistant's voice are in
> **German** by design — this is a German-speaking Alexa clone. All docs,
> configuration and code structure are in English.

## Features

**Real:**
- Weather via [Open-Meteo](https://open-meteo.com) (free, no API key) — current
  conditions plus a 5-day forecast with hourly temperature and rain analysis
- Clock / date / analog clock
- Timers & alarms with a soft continuous tone until you say "Alexa stop"
- "Bello" / "Wuff" dog-bark function (plays `dog.mp3`)
- Browser quick-links open the real page in your default browser
- Real YouTube embedded directly in the main window on macOS (with WebKit/PyObjC)
- Local music playback (when MP3s are present)
- Spotify control + now-playing + cover art (when configured)
- Text-to-speech (with `pyttsx3`) / microphone input (with `SpeechRecognition`)
- Notes

**Simulated / fallback:**
- Music visualizer bars (always animated, even during real playback)
- Fake playlist when neither Spotify nor local files are available
- In-window browser view (real pages open externally, not rendered in PyGame)

## Requirements

- Python 3.9+
- `pygame` (required)
- Everything else is optional — if an optional library is missing, the app
  switches to text/simulation mode automatically and does not crash.

## Installation

```bash
git clone https://github.com/<your-user>/echo-show-notebook.git
cd echo-show-notebook

# (recommended) virtual environment
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# required
pip install pygame

# or install everything optional at once
pip install -r requirements.txt
```

Optional extras and their platform notes are documented in
[`requirements.txt`](requirements.txt). PyAudio (microphone) in particular is
platform dependent:

```bash
# macOS
brew install portaudio && pip install pyaudio
# Debian/Ubuntu
sudo apt install portaudio19-dev && pip install pyaudio
```

## Running

```bash
python3 echo_show.py
```

Press `?` for the keyboard-shortcut overlay.

### Evil mode (optional, just for fun)

`echo_show_evil.py` loads the app and monkey-patches the assistant to be
sarcastic and grumpy without touching the original file. The snarky lines are
German (the app speaks German):

```bash
python3 echo_show_evil.py
```

Tune the intensity with `EVIL_LEVEL` (0–2) at the top of that file.

## Controls

- **Type + Enter** — send a command, e.g. `Alexa, zeig Wetter`
- **Spacebar** — microphone (only if `SpeechRecognition` + PyAudio are installed)
- **F11** — fullscreen · **Esc** — Home / leave fullscreen
- **Shortcuts** (when the input field is empty): `H` Home `U` Clock `M` Music
  `B` Browser `W` Weather `T` Timer `A` Alarm `V` Vacation `S` Settings
  `N` Notes
- **+ / −** — volume for music and the Alexa voice

A light-blue animated Alexa bar appears at the bottom when "Alexa" is detected
or the app is waiting for an answer.

### Example voice commands (German)

- `Alexa, Timer` → Alexa asks back; then e.g. `10 Minuten` or `10.00`
- `Alexa, Wecker` → Alexa asks back; then e.g. `10.00` or `in 10 Minuten`
- `Alexa, stop` stops a ringing timer or alarm
- `Alexa, wann regnet es?` or `Alexa, wie viel Grad wird es morgen früh?`
- `Alexa, Bello` or `Alexa, mach Wuff`
- `Alexa, YouTube` opens real YouTube in the main window (if WebKit/PyObjC are installed)

## Configuration

Edit the `CONFIG` block at the top of `echo_show.py`:

| Key | Description |
| --- | --- |
| `weather_auto_location` | `True` = detect location automatically (adapts to wherever your laptop is online) |
| `weather_use_gps` | `True` = use macOS CoreLocation for a much more precise location than IP (falls back to IP). Optional: `brew install corelocationcli` |
| `weather_city` | Fallback city if auto-detection fails or `weather_auto_location=False` |
| `music_folder` | Folder with your own MP3s (fallback without Spotify) |
| `start_fullscreen` | Start directly in fullscreen |
| `voice_wakeword` | Continuously listen for "Alexa" (needs `SpeechRecognition` + PyAudio) |
| `standby_mode` | `brightness` / `display_sleep` / `black` |
| `tts_voice` | macOS voice name (e.g. `Anna`, `Markus`, `Petra`, `Petra (Premium)`). Empty = best German voice. List voices: `say -v "?"`. See [Voice setup](#voice-setup-text-to-speech--microphone) — the voice may need to be downloaded first. |
| `whisper_model` | Offline speech recognition with Whisper (`small` / `medium` / `large-v3`). Empty = use Google online |
| `clock_24h` | 24-hour clock format |

Timers and alarms are saved automatically to `echo_show_state.json` next to the
app and restored on the next launch.

### Voice setup (text-to-speech + microphone)

The assistant speaks **German**. How speech is produced depends on your OS:

**macOS (recommended) — nothing to pip-install.**
The app uses the built-in `say` command (`say -v <voice> -o file && afplay`).
You only need the voice itself installed:

1. List the voices you currently have:
   ```bash
   say -v "?"
   ```
   German voices end in `de_DE` (e.g. `Anna`, `Markus`, `Petra`).
2. If no good German voice is listed, download one:
   **System Settings → Accessibility → Spoken Content → System Voice →
   Manage Voices…** → search "German" / "Deutsch" and download a voice
   (the *Premium* / *Enhanced* variants sound far better, e.g. `Petra (Premium)`).
3. Set it in `CONFIG`:
   ```python
   "tts_voice": "Petra (Premium)",   # exact name from `say -v "?"`, or "" to auto-pick the best German voice
   ```
   Test it directly:
   ```bash
   say -v "Petra (Premium)" "Hallo, ich bin deine Echo Show."
   ```

**Windows / Linux — uses `pyttsx3`.**
```bash
pip install pyttsx3
# Linux additionally needs an espeak backend:
sudo apt install espeak        # or: espeak-ng
```
On Windows `tts_voice` matches an installed SAPI5 voice name; on Linux it uses
espeak voices. Leave `tts_voice` empty to let the app auto-pick.

If no working voice is found, the app simply stays silent — it still shows all
text on screen and does not crash.

**Microphone input (optional, for spoken commands).**
This is separate from the voice output and needs PyAudio:
```bash
# macOS
brew install portaudio && pip install SpeechRecognition pyaudio
# Debian/Ubuntu
sudo apt install portaudio19-dev && pip install SpeechRecognition pyaudio
```
Speech is recognised in German (Google online by default, or Whisper offline if
`whisper_model` is set in `CONFIG`).

### Spotify setup (for real music)

Spotify does not render audio inside PyGame. Instead the app controls a running
Spotify device (desktop app or phone) via the Web API and shows the real track,
cover and progress.

1. A Spotify **Premium** account is required for play/pause/skip/volume.
2. Create an app at <https://developer.spotify.com/dashboard>.
3. Add this exact Redirect URI there: `http://127.0.0.1:8888/callback`
4. Provide your credentials — **recommended via `.env`:**
   ```bash
   cp .env.example .env
   # then edit .env and fill in SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET
   ```
   Environment variables (`SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`,
   `SPOTIFY_REDIRECT_URI`) override the empty defaults in `CONFIG`.
5. Start the app → on first run the browser opens for login.
6. Start playback on any Spotify device once so an "active device" exists. The
   app then controls it.

Without these steps the app uses local MP3s or the simulation.

> **Security:** never commit real credentials. `.env` is git-ignored. If a
> secret ever ends up in your git history, rotate it in the Spotify dashboard.

### Add your own music (without Spotify)

Drop `.mp3`, `.ogg` or `.wav` files into the `music/` folder. They are detected
on startup and played back for real via `pygame.mixer` (prev/play/pause/next/
volume all work).

## Project structure

```
echo-show-notebook/
├── echo_show.py        # the whole app (single file)
├── echo_show_evil.py   # optional "evil mode" wrapper (monkey-patch)
├── dog.mp3             # bark sound for the Bello/Wuff command
├── music/             # drop your own audio here (git-ignored)
├── requirements.txt
├── .env.example       # copy to .env for Spotify credentials
├── .gitignore
└── LICENSE            # MIT
```

## Possible improvements

- Change the weather location by voice
- Multiple alarms
- Read battery / Wi-Fi status for real (`psutil`)
- More themes
- Offline speech recognition with Vosk instead of Google

## License

[MIT](LICENSE)
