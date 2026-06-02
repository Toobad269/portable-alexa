# Local music folder

Drop `.mp3`, `.ogg` or `.wav` files in here.

On startup they are detected and played back for real via `pygame.mixer`
(previous / play / pause / next / volume all work). This is the fallback used
when Spotify is not configured.

Audio files in this folder are git-ignored on purpose — do not commit
copyrighted music.
