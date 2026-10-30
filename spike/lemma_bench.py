"""Throwaway test of base-form (lemma) lookup for English <-> Spanish. Not part of the plugin.

Needs, from spike/dict_bench.py and the download step: /tmp/kt-dict/{en,en-es-indexed,es-en-indexed}.sqlite3
and kaikki-es.jsonl (kaikki.org Spanish dump, CC BY-SA 4.0 and GFDL).
Run: python3 spike/lemma_bench.py
"""
import json
import os
import sqlite3
import time

D = "/tmp/kt-dict"
OUT = f"{D}/lemmas.sqlite3"

EN = ["house", "houses", "went", "running", "better", "children", "mice", "was", "ate", "bigger",
      "cats", "studies", "walked", "taken", "feet", "wolves", "zzzxq"]
ES = ["casa", "casas", "hablé", "comimos", "bonitas", "niños", "fui", "tengo", "dijeron", "pequeñas",
      "canciones", "vivimos", "escribió", "mejores", "perros", "gatas", "comiendo", "zzzxq"]


def mb(path):
    return os.path.getsize(path) / 1024 / 1024


def build():
    if os.path.exists(OUT):
        os.remove(OUT)
    db = sqlite3.connect(OUT)
    db.execute("create table en_lemma(form text, lemma text)")
    db.execute("create table es_lemma(form text, lemma text)")

    t0 = time.perf_counter()
    src = sqlite3.connect(f"file:{D}/en.sqlite3?mode=ro", uri=True)
    rows = src.execute(
        "select distinct lower(f.other_written), lower(e.written_rep) from form f join entry e on e.lexentry = f.lexentry "
        "where f.other_written is not null and lower(f.other_written) != lower(e.written_rep)")
    db.executemany("insert into en_lemma values (?, ?)", rows)
    print(f"English: {db.execute('select count(*) from en_lemma').fetchone()[0]} pairs from WikDict, {time.perf_counter() - t0:.1f} s")

    t0 = time.perf_counter()
    seen, lines = set(), 0
    for line in open(f"{D}/kaikki-es.jsonl", encoding="utf-8"):
        lines += 1
        entry = json.loads(line)
        for sense in entry.get("senses", []):
            for target in sense.get("form_of", []):
                pair = (entry["word"].lower(), target["word"].lower())
                if pair[0] != pair[1]:
                    seen.add(pair)
    db.executemany("insert into es_lemma values (?, ?)", seen)
    print(f"Spanish: {lines} dump entries, {len(seen)} pairs from kaikki.org, {time.perf_counter() - t0:.1f} s")

    db.execute("create index en_idx on en_lemma(form)")
    db.execute("create index es_idx on es_lemma(form)")
    db.commit()
    db.close()
    print(f"lemma file: {mb(OUT):.0f} MB")


def resolve(pair_db, lemma_table, lemmas, word):
    """Direct lookup first. If nothing is found, try each base form of the word."""
    q = "select trans_list from simple_translation where written_rep = ? limit 1"
    hit = pair_db.execute(q, (word,)).fetchone()
    if hit:
        return "direct", None, hit[0]
    for (lemma,) in lemmas.execute(f"select lemma from {lemma_table} where form = ?", (word,)).fetchall():
        hit = pair_db.execute(q, (lemma,)).fetchone()
        if hit:
            return "via lemma", lemma, hit[0]
    return "not found", None, None


def report(name, pair_path, lemma_table, words):
    pair_db = sqlite3.connect(f"file:{pair_path}?mode=ro", uri=True)
    lemmas = sqlite3.connect(f"file:{OUT}?mode=ro", uri=True)
    direct = via = 0
    t0 = time.perf_counter()
    for _ in range(50):
        for w in words:
            resolve(pair_db, lemma_table, lemmas, w)
    ms = (time.perf_counter() - t0) / (50 * len(words)) * 1000
    print(f"== {name}")
    for w in words:
        kind, lemma, trans = resolve(pair_db, lemma_table, lemmas, w)
        direct += kind == "direct"
        via += kind == "via lemma"
        shown = " ".join(trans.split())[:40] if trans else ""
        print(f"  {w:12} {kind:10} {lemma or '':10} {shown}")
    print(f"  direct {direct}, via lemma {via}, not found {len(words) - direct - via} of {len(words)}; {ms:.3f} ms per lookup")


build()
report("English -> Spanish", f"{D}/en-es-indexed.sqlite3", "en_lemma", EN)
report("Spanish -> English", f"{D}/es-en-indexed.sqlite3", "es_lemma", ES)
