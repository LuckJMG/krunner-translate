"""Builds dictionary.sqlite3 (English and Spanish) for the runner. Runs once on the developer machine.

Input folder, downloaded by hand (licenses: WikDict CC BY-SA, kaikki.org CC BY-SA 4.0 and GFDL):
  en-es.sqlite3, es-en.sqlite3, en.sqlite3   https://download.wikdict.com/dictionaries/sqlite/2/<name>.sqlite3
  kaikki-es.jsonl                            https://kaikki.org/dictionary/Spanish/kaikki.org-dictionary-Spanish.jsonl
Run: python3 -I tools/build_dictionary.py <input folder> <output file>
"""
import json
import os
import sqlite3
import sys

FILES = ["en-es.sqlite3", "es-en.sqlite3", "en.sqlite3", "kaikki-es.jsonl"]


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


def english_lemmas(src):
    rows = src.execute(
        "select distinct lower(f.other_written), lower(e.written_rep) from form f join entry e on e.lexentry = f.lexentry "
        "where f.other_written is not null and lower(f.other_written) != lower(e.written_rep)")
    return [("en", form, lemma) for form, lemma in rows]


def spanish_lemmas(jsonl_path):
    pairs = set()
    for line in open(jsonl_path, encoding="utf-8"):
        entry = json.loads(line)
        for sense in entry.get("senses", []):
            for target in sense.get("form_of", []):
                pair = (entry["word"].lower(), target["word"].lower())
                if pair[0] != pair[1]:
                    pairs.add(pair)
    return [("es", form, lemma) for form, lemma in pairs]


def main(folder, output):
    for name in FILES:
        if not os.path.exists(f"{folder}/{name}"):
            sys.exit(f"Missing input file: {folder}/{name}")
    if os.path.exists(output):
        os.remove(output)
    db = sqlite3.connect(output)
    db.execute("create table meaning(direction text, word text, translation text, sense text, score real)")
    db.execute("create table lemma(lang text, form text, lemma text)")
    # Read by the runner to know the installed languages. A scan of `meaning` would take 10 ms.
    db.execute("create table language(code text)")
    db.executemany("insert into language values (?)", [("en",), ("es",)])
    for direction in ("en-es", "es-en"):
        db.executemany("insert into meaning values (?, ?, ?, ?, ?)", meanings(read_only(f"{folder}/{direction}.sqlite3"), direction))
    db.executemany("insert into lemma values (?, ?, ?)", english_lemmas(read_only(f"{folder}/en.sqlite3")))
    db.executemany("insert into lemma values (?, ?, ?)", spanish_lemmas(f"{folder}/kaikki-es.jsonl"))
    db.execute("create index meaning_idx on meaning(direction, word)")
    db.execute("create index lemma_idx on lemma(lang, form)")
    db.commit()
    check(db)
    db.execute("vacuum")
    db.close()
    print(f"Wrote {output}: {os.path.getsize(output) / 1024 / 1024:.0f} MB")


def check(db):
    """Stops with an error if the output is wrong."""
    count = lambda sql, *args: db.execute(sql, args).fetchone()[0]
    assert count("select count(*) from meaning where direction = 'en-es' and word = 'house' and translation = 'casa'") == 1
    assert count("select count(*) from lemma where lang = 'es' and form = 'casas' and lemma = 'casa'") == 1
    assert count("select count(*) from lemma where lang = 'en' and form = 'houses' and lemma = 'house'") == 1
    assert count("select count(*) from language") == 2
    assert count("select count(*) from meaning") > 100_000
    assert count("select count(*) from lemma") > 100_000
    assert count("select count(*) from (select 1 from meaning group by direction, word, translation having count(*) > 1)") == 0
    print("Self-check passed")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
