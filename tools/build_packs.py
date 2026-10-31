"""Builds the language packs, and merges packs into dictionary.sqlite3. Runs on the developer machine.

A pack is one gzip file with one SQLite file inside. packs.json lists every pack (file, size, SHA-256) and the data format number.
  meaning-<from>-<to>   table `meaning`: one translation direction, from a WikDict pair file
  lemma-<lang>          table `lemma`: the base forms of one language
A dictionary holds the tables `meaning`, `lemma` and `language`. `add` in the program does the same merge as `merge` here.

Input folder, downloaded by hand (licenses: WikDict CC BY-SA, kaikki.org CC BY-SA 4.0 and GFDL):
  <from>-<to>.sqlite3 for each pair in PAIRS, en.sqlite3, fr.sqlite3   https://download.wikdict.com/dictionaries/sqlite/2/<name>.sqlite3
  kaikki-es.jsonl                                                      https://kaikki.org/dictionary/Spanish/kaikki.org-dictionary-Spanish.jsonl
  kaikki-fr.jsonl                                                      https://kaikki.org/dictionary/French/kaikki.org-dictionary-French.jsonl
  kaikki-en.jsonl                                                      https://kaikki.org/dictionary/English/kaikki.org-dictionary-English.jsonl
Run:
  python3 -I tools/build_packs.py packs <input folder> <pack folder>
  python3 -I tools/build_packs.py merge <pack folder> <output file> <language> <language>...
"""
import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import unicodedata

FORMAT = 1  # An older program must refuse packs with a higher number.
MEANING = "create table meaning(direction text, word text, translation text, sense text, score real)"
LEMMA = "create table lemma(lang text, form text, lemma text)"
PAIRS = ["en-es", "es-en", "fr-en", "en-fr", "fr-es", "es-fr"]


def read_only(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def meanings(src, direction):
    """One (direction, word, translation, sense, score) per word of each translation group. Highest score wins."""
    best = {}
    rows = src.execute("select lower(written_rep), trans_list, sense, score from translation where trans_list is not null")
    for word, trans_list, sense, score in rows:
        score = float(score or 0)
        for translation in (t.strip() for t in trans_list.split(" | ")):
            key = (word, translation)
            if translation and (key not in best or score > best[key][1]):
                best[key] = (sense or "", score)
    return [(direction, word, translation, sense, score) for (word, translation), (sense, score) in best.items()]


def wikdict_lemmas(lang, folder):
    src = read_only(f"{folder}/{lang}.sqlite3")
    rows = src.execute(
        "select distinct lower(f.other_written), lower(e.written_rep) from form f join entry e on e.lexentry = f.lexentry "
        "where f.other_written is not null and lower(f.other_written) != lower(e.written_rep)")
    return [(lang, form, lemma) for form, lemma in rows]


def kaikki_lemmas(lang, folder):
    pairs = set()
    for line in open(f"{folder}/kaikki-{lang}.jsonl", encoding="utf-8"):
        entry = json.loads(line)
        for sense in entry.get("senses", []):
            for target in sense.get("form_of", []):
                pair = (entry["word"].lower(), target["word"].lower())
                if pair[0] != pair[1]:
                    pairs.add(pair)
    return [(lang, form, lemma) for form, lemma in sorted(pairs)]  # sorted: the same dump gives the same pack bytes


def both_lemmas(lang, folder):
    """WikDict has the forms of nouns and adjectives. kaikki.org has the verb forms too. Only some pairs are in both."""
    return sorted(set(wikdict_lemmas(lang, folder)) | set(kaikki_lemmas(lang, folder)))


# Spanish has no usable base forms in WikDict, so it comes from the kaikki.org dump. English and French use both sources.
LEMMAS = {"en": both_lemmas, "es": kaikki_lemmas, "fr": both_lemmas}


def plain(word):
    """The word without accents: `todavía` becomes `todavia`."""
    return "".join(char for char in unicodedata.normalize("NFD", word) if not unicodedata.combining(char))


def accent_lemmas(lang, lemmas, headwords):
    """Rows that map a word without accents to the real word, so `tr todavia` finds `todavía` and `tr esta` also finds `estar`."""
    rows = {(lang, plain(form), lemma) for _, form, lemma in lemmas if plain(form) != form}
    rows |= {(lang, plain(word), word) for word in headwords if plain(word) != word}
    return [row for row in rows if row[1] != row[2]]  # A word never maps to itself.


def write_pack(pack_folder, name, create_sql, rows):
    """Writes <name>.sqlite3.gz. The gzip header has no time, so the same rows give the same SHA-256."""
    path = f"{pack_folder}/{name}.sqlite3"
    db = sqlite3.connect(path)
    db.execute(create_sql)
    db.executemany(f"insert into {name.split('-')[0]} values ({','.join('?' * len(rows[0]))})", rows)
    db.commit()
    db.execute("vacuum")
    db.close()
    with open(path, "rb") as src, open(path + ".gz", "wb") as out:
        with gzip.GzipFile(filename="", mode="wb", fileobj=out, compresslevel=9, mtime=0) as gz:
            shutil.copyfileobj(src, gz)
    os.remove(path)
    data = open(path + ".gz", "rb").read()
    return {"file": f"{name}.sqlite3.gz", "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def open_pack(pack_folder, manifest, name):
    """The pack as an in-memory database, after a SHA-256 check."""
    data = open(f"{pack_folder}/{manifest['packs'][name]['file']}", "rb").read()
    assert hashlib.sha256(data).hexdigest() == manifest["packs"][name]["sha256"], f"wrong checksum: {name}"
    db = sqlite3.connect(":memory:")
    db.deserialize(gzip.decompress(data))
    return db


def build_packs(folder, pack_folder):
    os.makedirs(pack_folder, exist_ok=True)
    packs = {}
    headwords = {lang: set() for lang in LEMMAS}
    for pair in PAIRS:
        name = f"meaning-{pair}"
        rows = meanings(read_only(f"{folder}/{pair}.sqlite3"), pair)
        headwords[pair.split("-")[0]].update(row[1] for row in rows)
        packs[name] = write_pack(pack_folder, name, MEANING, rows)
    for lang, read in LEMMAS.items():
        name = f"lemma-{lang}"
        lemmas = read(lang, folder)
        packs[name] = write_pack(pack_folder, name, LEMMA, sorted(set(lemmas) | set(accent_lemmas(lang, lemmas, headwords[lang]))))
    manifest = {"format": FORMAT, "packs": packs}
    json.dump(manifest, open(f"{pack_folder}/packs.json", "w"), indent=2, sort_keys=True)
    check_packs(pack_folder, manifest)
    for name, pack in packs.items():
        print(f"{name}: {pack['size'] / 1024 / 1024:.1f} MB")


def check_packs(pack_folder, manifest):
    """Stops with an error if a pack is wrong."""
    def count(name, sql):
        return open_pack(pack_folder, manifest, name).execute(sql).fetchone()[0]
    assert count("meaning-en-es", "select count(*) from meaning where word = 'house' and translation = 'casa'") == 1
    assert count("meaning-fr-en", "select count(*) from meaning where word = 'maison' and translation = 'house'") == 1
    assert count("lemma-en", "select count(*) from lemma where form = 'houses' and lemma = 'house'") == 1
    for form, lemma in [("walked", "walk"), ("ran", "run"), ("was", "be"), ("went", "go")]:
        assert count("lemma-en", f"select count(*) from lemma where form = '{form}' and lemma = '{lemma}'") == 1, form
    assert count("lemma-es", "select count(*) from lemma where form = 'casas' and lemma = 'casa'") == 1
    assert count("lemma-fr", "select count(*) from lemma where form = 'maisons' and lemma = 'maison'") == 1
    # Words without accents map to the real word.
    for pack, form, lemma in [("lemma-es", "todavia", "todavía"), ("lemma-es", "esta", "estar"), ("lemma-fr", "cafe", "café"), ("lemma-fr", "mange", "manger")]:
        assert count(pack, f"select count(*) from lemma where form = '{form}' and lemma = '{lemma}'") == 1, form
    for form, lemma in [("mangeons", "manger"), ("suis", "être"), ("allé", "aller"), ("belles", "belle")]:
        assert count("lemma-fr", f"select count(*) from lemma where form = '{form}' and lemma = '{lemma}'") == 1, form
    for name in manifest["packs"]:
        table = name.split("-")[0]
        assert count(name, f"select count(*) from {table}") > 50_000, name
        if table == "meaning":
            assert count(name, "select count(*) from (select 1 from meaning group by word, translation having count(*) > 1)") == 0, name
    print("Self-check passed")


def merge(pack_folder, output, langs):
    manifest = json.load(open(f"{pack_folder}/packs.json"))
    assert manifest["format"] == FORMAT, f"pack format {manifest['format']}, this script reads {FORMAT}"
    names = [f"lemma-{lang}" for lang in langs] + [f"meaning-{a}-{b}" for a in langs for b in langs if a != b]
    missing = [name for name in names if name not in manifest["packs"]]
    assert not missing, f"no pack for: {missing}"
    if os.path.exists(output):
        os.remove(output)
    db = sqlite3.connect(output)
    db.execute(MEANING)
    db.execute(LEMMA)
    # Read by the runner to know the installed languages. A scan of `meaning` would take 10 ms.
    db.execute("create table language(code text)")
    db.executemany("insert into language values (?)", [(lang,) for lang in langs])
    for name in names:
        table = name.split("-")[0]
        rows = open_pack(pack_folder, manifest, name).execute(f"select * from {table}")
        db.executemany(f"insert into {table} values ({','.join('?' * len(rows.description))})", rows)
    db.execute("create index meaning_idx on meaning(direction, word)")
    db.execute("create index lemma_idx on lemma(lang, form)")
    db.commit()
    count = lambda sql: db.execute(sql).fetchone()[0]
    assert count("select count(*) from language") == len(langs)
    assert count("select count(*) from (select 1 from meaning group by direction, word, translation having count(*) > 1)") == 0
    assert count("select count(*) from meaning") > 100_000 and count("select count(*) from lemma") > 100_000
    db.execute("vacuum")
    db.close()
    print(f"Wrote {output}: {os.path.getsize(output) / 1024 / 1024:.0f} MB")


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) == 3 and args[0] == "packs":
        build_packs(args[1], args[2])
    elif len(args) >= 4 and args[0] == "merge":
        merge(args[1], args[2], args[3:])
    else:
        sys.exit(__doc__)
