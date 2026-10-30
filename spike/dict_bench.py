"""Throwaway measurement of dictionary data for English <-> Spanish. Not part of the plugin.

Needs the files in /tmp/kt-dict (WikDict en-es, es-en, en, es and FreeDict spa-eng StarDict).
Run: python3 spike/dict_bench.py
"""
import gzip
import os
import shutil
import sqlite3
import struct
import time

D = "/tmp/kt-dict"

# Words that can fail: common words, phrases, inflected forms, ambiguous words
EN = ["house", "hello", "taxi", "no", "pan", "chocolate", "tomorrow", "computer", "thank you",
      "good morning", "ice cream", "running", "houses", "went", "better", "quickly", "zzzxq"]
ES = ["casa", "gracias", "taxi", "no", "pan", "chocolate", "mañana", "ordenador", "buenas noches",
      "por favor", "de nada", "hablé", "casas", "comimos", "rápidamente", "bonito", "zzzxq"]


def rss_mb():
    for line in open("/proc/self/status"):
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) / 1024


def mb(path):
    return os.path.getsize(path) / 1024 / 1024


class WikDict:
    """simple_translation(written_rep, trans_list) in a pair database, read-only."""

    def __init__(self, path):
        self.db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)

    def lookup(self, word):
        row = self.db.execute("select trans_list from simple_translation where written_rep = ? limit 1", (word,)).fetchone()
        return row[0] if row else None


class StarDict:
    """StarDict .idx.gz (word NUL offset size, big-endian) plus .dict or .dict.dz, loaded into memory."""

    def __init__(self, stem):
        idx = gzip.open(stem + ".idx.gz").read()
        dict_path = stem + ".dict.dz" if os.path.exists(stem + ".dict.dz") else stem + ".dict"
        self.data = gzip.open(dict_path).read() if dict_path.endswith(".dz") else open(dict_path, "rb").read()
        self.index = {}
        i = 0
        while i < len(idx):
            end = idx.index(b"\0", i)
            off, size = struct.unpack(">II", idx[end + 1:end + 9])
            self.index[idx[i:end].decode().lower()] = (off, size)
            i = end + 9

    def lookup(self, word):
        hit = self.index.get(word.lower())
        return self.data[hit[0]:hit[0] + hit[1]].decode(errors="replace") if hit else None


def short(text):
    return None if text is None else " ".join(text.split())[:50]


def coverage(name, source, words):
    found = [w for w in words if source.lookup(w)]
    print(f"  {name}: found {len(found)}/{len(words)}; missing: {[w for w in words if w not in found]}")


def latency(source, words, rounds=20):
    t0 = time.perf_counter()
    for _ in range(rounds):
        for w in words:
            source.lookup(w)
    return (time.perf_counter() - t0) / (rounds * len(words)) * 1000


print("== File sizes (MB)")
for f in ["en-es.sqlite3", "es-en.sqlite3", "en.sqlite3", "es.sqlite3"]:
    print(f"  {f}: {mb(f'{D}/{f}'):.0f}")
print(f"  FreeDict eng-spa .dict: {mb(f'{D}/eng-spa/eng-spa.dict'):.0f}, spa-eng .dict.dz: {mb(f'{D}/spa-eng/spa-eng.dict.dz'):.2f}")

print("== Opening cost and memory")
base = rss_mb()
t0 = time.perf_counter()
en_es = WikDict(f"{D}/en-es.sqlite3")
es_en = WikDict(f"{D}/es-en.sqlite3")
print(f"  WikDict open x2: {(time.perf_counter() - t0) * 1000:.1f} ms")
t0 = time.perf_counter()
en_es.lookup("house")
print(f"  first lookup (no index, cold): {(time.perf_counter() - t0) * 1000:.1f} ms")
print(f"  rss delta after open and one lookup: {rss_mb() - base:.0f} MB")
for name, d in (("en-es", en_es), ("es-en", es_en)):
    n = d.db.execute("select count(*) from simple_translation").fetchone()[0]
    print(f"  {name}: {n} rows")
base = rss_mb()
t0 = time.perf_counter()
spa_eng = StarDict(f"{D}/spa-eng/spa-eng")
print(f"  FreeDict spa-eng load: {(time.perf_counter() - t0) * 1000:.0f} ms, {len(spa_eng.index)} headwords, rss delta {rss_mb() - base:.0f} MB")

print("== Coverage")
print(" English -> Spanish")
coverage("WikDict en-es", en_es, EN)
print(" Spanish -> English")
coverage("WikDict es-en", es_en, ES)
coverage("FreeDict spa-eng", spa_eng, ES)

print("== Sample results (WikDict)")
for w in ("house", "no", "pan", "running"):
    print(f"  en-es {w!r}: {short(en_es.lookup(w))}")
for w in ("casa", "no", "pan", "hablé"):
    print(f"  es-en {w!r}: {short(es_en.lookup(w))}")

print("== Lookup latency (ms per lookup, warm)")
print(f"  WikDict en-es, no index: {latency(en_es, EN):.2f}")
print(f"  WikDict es-en, no index: {latency(es_en, ES):.2f}")
print(f"  FreeDict spa-eng, in memory: {latency(spa_eng, ES, 200):.4f}")

print("== WikDict with an index on written_rep (copy in /tmp)")
for name in ("en-es", "es-en"):
    src, dst = f"{D}/{name}.sqlite3", f"{D}/{name}-indexed.sqlite3"
    shutil.copy(src, dst)
    db = sqlite3.connect(dst)
    db.execute("create index idx_wr on simple_translation(written_rep)")
    db.commit()
    db.close()
    d = WikDict(dst)
    words = EN if name == "en-es" else ES
    print(f"  {name}: file {mb(src):.0f} -> {mb(dst):.0f} MB, latency {latency(d, words):.4f} ms")

print("== English inflection data in en.sqlite3 (WikDict language database)")
db = sqlite3.connect(f"file:{D}/en.sqlite3?mode=ro", uri=True)
print(f"  form rows: {db.execute('select count(*) from form').fetchone()[0]}")
for w in ("running", "houses", "went", "better"):
    rows = db.execute("select lexentry, inflection from form where other_written = ? limit 3", (w,)).fetchall()
    print(f"  {w!r}: {rows if rows else 'no inflection row'}")
db = sqlite3.connect(f"file:{D}/es.sqlite3?mode=ro", uri=True)
print(f"  Spanish form rows: {db.execute('select count(*) from form').fetchone()[0]}")
print(f"peak rss of this process: {[l for l in open('/proc/self/status') if l.startswith('VmHWM')][0].split()[1]} kB")
