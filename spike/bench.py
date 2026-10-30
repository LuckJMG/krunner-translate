"""Throwaway measurement of Argos Translate and Lingua. Not part of the plugin.

Run each mode in its own process so memory numbers do not mix:
    /tmp/krunner-translate-spike/bin/python -I spike/bench.py <mode>
Modes: setup, argos, lingua-all, lingua-subset, lingua-subset-low
"""
import os
import sys
import time
import statistics

# Keep every download in /tmp, not in the home directory. Set before importing Argos.
for var, sub in (("XDG_DATA_HOME", "kt-data"), ("XDG_CACHE_HOME", "kt-cache"), ("XDG_CONFIG_HOME", "kt-cfg")):
    os.environ[var] = f"/tmp/{sub}"

LANGS = ["en", "es", "fr"]

# (from, to, text): about twenty single words and short sentences
CASES = [
    ("en", "es", "hello"),
    ("en", "es", "good morning"),
    ("en", "es", "where is the train station?"),
    ("en", "es", "taxi"),
    ("en", "fr", "no"),
    ("en", "fr", "I would like a coffee"),
    ("en", "fr", "thank you very much"),
    ("es", "en", "gracias"),
    ("es", "en", "no"),
    ("es", "en", "¿Cuánto cuesta esto?"),
    ("es", "en", "la casa es azul"),
    ("es", "fr", "buenas noches"),
    ("es", "fr", "chocolate"),
    ("fr", "en", "bonjour"),
    ("fr", "en", "chocolat"),
    ("fr", "en", "je ne sais pas"),
    ("fr", "en", "où est la gare ?"),
    ("fr", "es", "merci beaucoup"),
    ("fr", "es", "le chat dort"),
    ("en", "es", "I do not know"),
]


def rss_mb():
    """Current resident memory of this process in MB."""
    for line in open("/proc/self/status"):
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) / 1024


def setup():
    import argostranslate.package as pkg

    pkg.update_package_index()
    for a in LANGS:
        for b in LANGS:
            if a != b:
                print(f"{a}->{b}: installed={pkg.install_package_for_language_pair(a, b)}")
    print("installed packages:", sorted(f"{p.from_code}->{p.to_code}" for p in pkg.get_installed_packages()))


def argos():
    import argostranslate.translate as tr

    base = rss_mb()
    print(f"rss before: {base:.0f} MB")
    times = []
    for i, (src, dst, text) in enumerate(CASES):
        t0 = time.perf_counter()
        out = tr.translate(text, src, dst)
        ms = (time.perf_counter() - t0) * 1000
        times.append(ms)
        print(f"{ms:7.0f} ms  {src}->{dst}  {text!r} -> {out!r}")
    print(f"first call (cold): {times[0]:.0f} ms")
    warm = times[1:]
    print(f"warm calls: median {statistics.median(warm):.0f} ms, max {max(warm):.0f} ms")
    print(f"rss after: {rss_mb():.0f} MB (delta {rss_mb() - base:.0f} MB)")


def lingua(subset, low):
    from lingua import IsoCode639_1, LanguageDetectorBuilder

    base = rss_mb()
    print(f"rss before: {base:.0f} MB")
    t0 = time.perf_counter()
    if subset:
        codes = [getattr(IsoCode639_1, code.upper()) for code in LANGS]
        builder = LanguageDetectorBuilder.from_iso_codes_639_1(*codes)
    else:
        builder = LanguageDetectorBuilder.from_all_languages()
    if low:
        builder = builder.with_low_accuracy_mode()
    detector = builder.build()
    print(f"build: {(time.perf_counter() - t0) * 1000:.0f} ms")
    times = []
    right = 0
    for src, _dst, text in CASES:
        t0 = time.perf_counter()
        values = detector.compute_language_confidence_values(text)
        times.append((time.perf_counter() - t0) * 1000)
        top = values[0]
        guess = top.language.iso_code_639_1.name.lower()
        right += guess == src
        mark = "ok " if guess == src else "BAD"
        print(f"{mark} expected {src} got {guess} conf {top.value:.2f}  {text!r}")
    print(f"first call (cold): {times[0]:.0f} ms")
    print(f"warm calls: median {statistics.median(times[1:]):.1f} ms, max {max(times[1:]):.1f} ms")
    print(f"correct: {right}/{len(CASES)}")
    print(f"rss after: {rss_mb():.0f} MB (delta {rss_mb() - base:.0f} MB)")


mode = sys.argv[1]
if mode == "setup":
    setup()
elif mode == "argos":
    argos()
elif mode == "lingua-all":
    lingua(subset=False, low=False)
elif mode == "lingua-subset":
    lingua(subset=True, low=False)
elif mode == "lingua-subset-low":
    lingua(subset=True, low=True)
else:
    sys.exit(f"unknown mode: {mode}")
