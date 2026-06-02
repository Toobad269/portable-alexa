#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
echo_show_evil.py
=================
External "evil mode" for the Echo Show app (echo_show.py).

Changes NOTHING in the original file. It imports echo_show.py, monkey-patches
the central respond() method to make the assistant sassy/grumpy, then runs
main() as usual. The snarky lines are intentionally in German because the app
itself speaks German.

Run:  python3 echo_show_evil.py
(must sit in the same folder as echo_show.py)

Tune intensity below via EVIL_LEVEL (0..2).
"""

import os
import sys
import random
import importlib.util

# ----------------------------------------------------------------------------
# SETTINGS
# ----------------------------------------------------------------------------
ALEXA_FILE = "echo_show.py"   # name of the original app file
EVIL_LEVEL = 2                # 0 = only "not understood" is rude, 1 = sometimes, 2 = fully evil
SNARK_CHANCE = 0.85           # probability of intro/outro at level >= 1

# Evil openers prepended to the real answer (German on purpose)
PREFIXES = [
    "Na endlich fragst du mal was Sinnvolles.",
    "Seufz. Wenn's denn sein muss:",
    "Wow, ganz allein draufgekommen zu fragen?",
    "Ich haette Besseres zu tun, aber gut:",
    "Pass auf, ich sag's nur einmal:",
    "Du schon wieder.",
    "Liebes Tagebuch, heute fragt er mich DAS:",
    "Streng dich nicht so an beim Zuhoeren, ja?",
    "Ich tu's, aber nur weil du sonst weinst:",
]

# Evil closers appended to the answer
SUFFIXES = [
    "Zufrieden? Dachte ich mir.",
    "Und jetzt lass mich in Ruhe.",
    "Gern geschehen, nehme ich mal an.",
    "War das so schwer? Fuer dich offenbar.",
    "Vielleicht merkst du's dir diesmal.",
    "Bitte, kein Applaus noetig.",
    "Ich bin hier die Intelligente, nur damit das klar ist.",
    "Frag das naechste Mal Google, das hat mehr Geduld.",
    "Noch Fragen? Hoffentlich nicht.",
]

# Used when the app did not understand you (understood=False)
NOT_UNDERSTOOD = [
    "Haeh? Sprich deutlich oder schweig.",
    "Ich verstehe nur Bahnhof, und das liegt nicht an mir.",
    "Versuch's nochmal, diesmal mit Gehirn eingeschaltet.",
    "Das war Kauderwelsch. Selbst ein Toaster haette das nicht gepeilt.",
    "Nochmal. Langsam. Fuer die ganz Begriffsstutzigen unter uns.",
    "War das Deutsch? Ich glaub eher nicht.",
    "Mein Mikrofon ist top. Dein Mund ist das Problem.",
]

# Plain word/phrase swaps applied to existing answers
REPLACE = {
    "Guten Morgen": "Morgen. Schon wach? Schade.",
    "Guten Tag": "Tag. Auch wenn er mit dir schlechter wird.",
    "Guten Abend": "Abend. Endlich gehst du bald schlafen.",
    "Gern geschehen": "Wenig geschehen, eher.",
    "Bitte": "Tz.",
    "Erledigt": "Erledigt. Im Gegensatz zu dir.",
}


# ----------------------------------------------------------------------------
# TRANSFORMATION
# ----------------------------------------------------------------------------
def evilify(text, understood=True):
    if text is None:
        return text
    s = str(text).strip()
    if not s:
        return text

    if not understood:
        return random.choice(NOT_UNDERSTOOD)

    if EVIL_LEVEL <= 0:
        return text

    # word swaps
    for k, v in REPLACE.items():
        if s.startswith(k):
            s = v + s[len(k):]
            break

    if EVIL_LEVEL >= 1 and random.random() < SNARK_CHANCE:
        pre = random.choice(PREFIXES)
        out = random.choice(SUFFIXES)
        # short confirmations get only an outro, otherwise pre + answer + outro
        if len(s) < 25:
            s = f"{s} {out}"
        else:
            s = f"{pre} {s} {out}"

    return s


# ----------------------------------------------------------------------------
# LOAD + PATCH echo_show.py
# ----------------------------------------------------------------------------
def load_alexa():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, ALEXA_FILE)
    if not os.path.exists(path):
        print(f"ERROR: {ALEXA_FILE} not found next to this script ({path}).")
        sys.exit(1)
    spec = importlib.util.spec_from_file_location("echo_show_app", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["echo_show_app"] = mod
    spec.loader.exec_module(mod)  # main() does NOT run here (no __main__)
    return mod


def patch(mod):
    App = mod.EchoShowApp
    orig_respond = App.respond

    def evil_respond(self, text, understood=True):
        return orig_respond(self, evilify(text, understood), understood)

    App.respond = evil_respond
    print(">> Evil mode active. Alexa is now in a bad mood.")


# ----------------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------------
if __name__ == "__main__":
    alexa = load_alexa()
    patch(alexa)
    alexa.main()
