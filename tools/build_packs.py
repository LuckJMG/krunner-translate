"""Builds the language packs, and merges packs into dictionary.sqlite3. Runs on the developer machine.

A pack is one gzip file with one SQLite file inside.
  meaning-<from>-<to>   table `meaning`: one translation direction, from a WikDict pair file
  lemma-<lang>          table `lemma`: the base forms of one language
The packs of one source language sit one after the other in one bundle file, bundle-<lang>.bin: its lemma pack and all
meaning-<lang>-* packs. packs.json lists every pack (bundle file, offset, size, SHA-256) and the data format number.
The program downloads only the byte range of each pack that it needs (HTTP Range request).
A dictionary holds the tables `meaning`, `lemma` and `language`. `add` in the program does the same merge as `merge` here.

Input folder, downloaded by hand (licenses: WikDict CC BY-SA, kaikki.org CC BY-SA 4.0 and GFDL):
  <from>-<to>.sqlite3 for each pair in PAIRS, <lang>.sqlite3 for en, fr, de          https://download.wikdict.com/dictionaries/sqlite/2/<name>.sqlite3
  kaikki-<lang>.jsonl for each language                                           https://kaikki.org/dictionary/<Language>/kaikki.org-dictionary-<Language>.jsonl
                                                                                  (<Language> is the English name, for example Spanish. `ku` is Northern Kurdish, `no` is Norwegian Bokm%C3%A5l. Chinese needs no dump.)
  opencc-<name>.txt for STCharacters, STPhrases, TSCharacters, TSPhrases          https://raw.githubusercontent.com/BYVoid/OpenCC/master/data/dictionary/<name>.txt
                                                                                  (OpenCC, Apache-2.0: Simplified and Traditional Chinese)
Run:
  python3 -I tools/build_packs.py packs <input folder> <pack folder>
  python3 -I tools/build_packs.py check <pack folder>        (the self-check alone, on packs that exist)
  python3 -I tools/build_packs.py merge <pack folder> <output file> <language> <language>...
"""
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import sys
import unicodedata

FORMAT = 2  # An older program must refuse packs with a higher number. 2: bundles with byte ranges (1: one file for each pack).
MEANING = "create table meaning(direction text, word text, translation text, sense text, score real)"
LEMMA = "create table lemma(lang text, form text, lemma text)"
# The dictionary file has no separate index for `lemma`: the table is its own index, and the file is 40% smaller. Packs have plain tables.
DICTIONARY_LEMMA = "create table lemma(lang text, form text, lemma text, primary key(lang, form, lemma)) without rowid"


def read_only(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def meanings(src, direction):
    """One (direction, word, translation, sense, score) per word of each translation group. Highest score wins."""
    best = {}
    rows = src.execute("select lower(written_rep), trans_list, sense, score from translation where trans_list is not null")
    for word, trans_list, sense, score in rows:
        word, score = no_stress(word), float(score or 0)
        for translation in (no_stress(t.strip()) for t in trans_list.split(" | ")):
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


def no_stress(text):
    """Wiktionary writes Russian words with a stress mark: `идти́`. Nobody types the mark, and it does not copy well."""
    return text.replace("\u0301", "") if re.search("[\u0400-\u04ff]", text) else text  # Spanish `é` is one character, so it stays.


def unstressed(word):
    return no_stress(word.lower())


# Tags of `forms` entries that are no inflected forms: a romanization (`aetós` for `αετός`), the headword with accents, a class of the inflection table.
NOISE_TAGS = {"romanization", "canonical", "class"}


def kaikki_lemmas(lang, folder, with_forms=False, skip_tags=NOISE_TAGS):
    """Pairs (form, base word) from a kaikki.org dump. The dump has an entry for many forms, and `form_of` points to the base word.
    With `with_forms`, the `forms` list of each base word counts too. Turkish, Polish and Dutch have most of their forms only there.
    A form with a tag in `skip_tags` does not count."""
    pairs = set()
    for line in open(f"{folder}/kaikki-{lang}.jsonl", encoding="utf-8"):
        entry = json.loads(line)
        word = unstressed(entry["word"])
        for sense in entry.get("senses", []):
            for target in sense.get("form_of", []):
                pairs.add((unstressed(entry["word"]), unstressed(target["word"])))
        for form in entry.get("forms", []) if with_forms else []:
            tags = form.get("tags", [])
            # Some entries list a placeholder of the inflection table instead of a form.
            if any("table-tags" in tag or tag == "inflection-template" or any(skip in tag for skip in skip_tags) for tag in tags):
                continue
            if form.get("form") not in (None, "-", "no-table-tags"):
                pairs.add((unstressed(form["form"]), word))
    return [(lang, form, lemma) for form, lemma in sorted(pairs) if form != lemma]  # sorted: the same dump gives the same pack bytes


def kaikki_with_forms(lang, folder):
    return kaikki_lemmas(lang, folder, with_forms=True)


def both_lemmas(lang, folder):
    """WikDict has the forms of nouns and adjectives. kaikki.org has the verb forms too. Only some pairs are in both."""
    return sorted(set(wikdict_lemmas(lang, folder)) | set(kaikki_lemmas(lang, folder)))


def no_lemmas(lang, folder):
    """Chinese has no inflection, so it has no base forms. The kaikki.org dump has only pinyin spellings for it."""
    return []


def kaikki_finnish(lang, folder):
    """A Finnish word has more than 2,000 forms, because of the possessive endings (`taloni`, `talossani`). Without them it has 100 times fewer."""
    return kaikki_lemmas(lang, folder, with_forms=True, skip_tags=NOISE_TAGS | {"possessive"})


# One line for each language: how to read its base forms. WikDict has usable base forms only for English, French and German.
# Spanish, Russian and Portuguese come from the kaikki.org dump alone. Chinese has none.
# All other languages also use the `forms` lists of the dump, because it has most of their forms only there. A new language is one line here, and the pairs follow from the table.
# `ku` is Northern Kurdish in the dump, and `no` is Norwegian Bokmål.
LANGUAGES = {"en": both_lemmas, "es": kaikki_lemmas, "fr": both_lemmas, "ru": kaikki_lemmas, "de": both_lemmas, "pt": kaikki_lemmas, "zh": no_lemmas,
             "it": kaikki_with_forms, "nl": kaikki_with_forms, "pl": kaikki_with_forms, "tr": kaikki_with_forms,
             "bg": kaikki_with_forms, "ca": kaikki_with_forms, "cs": kaikki_with_forms, "da": kaikki_with_forms, "el": kaikki_with_forms,
             "fi": kaikki_finnish, "ga": kaikki_with_forms, "id": kaikki_with_forms, "ja": kaikki_with_forms, "ku": kaikki_with_forms,
             "la": kaikki_with_forms, "lt": kaikki_with_forms, "mg": kaikki_with_forms, "no": kaikki_with_forms, "sv": kaikki_with_forms}
PAIRS = [f"{a}-{b}" for a in LANGUAGES for b in LANGUAGES if a != b]


# Letters that have no accent mark to remove. People type the plain letter for them: `lodz` for `łódź`, `kiz` for `kız`, `bjorn` for `bjørn`.
PLAIN_LETTERS = str.maketrans({"ł": "l", "ı": "i", "ø": "o", "æ": "ae"})


def plain(word):
    """The word without accents: `todavía` becomes `todavia`, `ё` becomes `е`, `łódź` becomes `lodz`.
    The Russian `й` stays, because it is a different letter. The Japanese marks of `が` stay too: `か` is another syllable."""
    folded = ""
    for char in unicodedata.normalize("NFD", word):
        if not unicodedata.combining(char) or char in "\u3099\u309a" or (char == "\u0306" and folded.endswith("и")):
            folded += char
    return unicodedata.normalize("NFC", folded).translate(PLAIN_LETTERS)


def accent_lemmas(lang, lemmas, headwords):
    """Rows that map a word without accents to the real word, so `tr todavia` finds `todavía` and `tr esta` also finds `estar`."""
    rows = {(lang, plain(form), lemma) for _, form, lemma in lemmas if plain(form) != form}
    rows |= {(lang, plain(word), word) for word in headwords if plain(word) != word}
    return [row for row in rows if row[1] != row[2]]  # A word never maps to itself.


def opencc_table(folder, *names):
    """The OpenCC words of the files as {key: first value}. A key can have several values. The first one is the main one."""
    table = {}
    for name in names:
        for line in open(f"{folder}/opencc-{name}.txt", encoding="utf-8"):
            if line.strip() and not line.startswith("#"):
                key, values = line.rstrip("\n").split("\t")
                table[key] = values.split(" ")[0]
    return table


def convert(word, table):
    """Replaces the longest known parts of the word, from left to right. A part that is not in the table stays."""
    longest, out, i = max(map(len, table)), "", 0
    while i < len(word):
        size = next((n for n in range(min(longest, len(word) - i), 0, -1) if word[i:i + n] in table), 1)
        out += table.get(word[i:i + size], word[i:i + size])
        i += size
    return out


def chinese_variants(lang, headwords, folder):
    """Rows from the Simplified and the Traditional spelling of each headword to the headword: `tr 汉字` finds `漢字`.
    The WikDict file mixes both scripts, and a word has only one of them."""
    to_traditional = opencc_table(folder, "STCharacters", "STPhrases")
    to_simplified = opencc_table(folder, "TSCharacters", "TSPhrases")
    rows = set()
    for word in headwords:
        for variant in (convert(word, to_traditional), convert(word, to_simplified)):
            if variant != word:
                rows.add((lang, variant, word))
    return rows


# Extra rows from the headwords: spellings that map to a headword. Every language gets the accent rows (see accent_lemmas).
VARIANTS = {"zh": chinese_variants}


def keep_phrase_rows(rows):
    """A form with a space stays only if its base word has a space too: `gave up` → `give up` stays, `bin gegangen worden` → `gehen` goes.
    The program looks up the whole text, so a tense written in several words is not typed. A phrase verb or a phrase noun is."""
    return [row for row in rows if " " not in row[1] or " " in row[2]]


def make_pack(pack_folder, name, create_sql, rows):
    """The gzip bytes of one pack. The gzip header has no time, so the same rows give the same bytes."""
    path = f"{pack_folder}/tmp-{name}.sqlite3"
    db = sqlite3.connect(path)
    db.execute(create_sql)
    table = name.split("-")[0]
    columns = len(db.execute(f"pragma table_info({table})").fetchall())  # A pack can have no rows, for example the base forms of Chinese.
    db.executemany(f"insert into {table} values ({','.join('?' * columns)})", rows)
    db.commit()
    db.execute("vacuum")
    db.close()
    with open(path, "rb") as src, io.BytesIO() as out:
        with gzip.GzipFile(filename="", mode="wb", fileobj=out, compresslevel=9, mtime=0) as gz:
            shutil.copyfileobj(src, gz)
        os.remove(path)
        return out.getvalue()


def open_pack(pack_folder, manifest, name):
    """The pack as an in-memory database, after a SHA-256 check."""
    pack = manifest["packs"][name]
    with open(f"{pack_folder}/{pack['file']}", "rb") as bundle:
        bundle.seek(pack["offset"])
        data = bundle.read(pack["size"])
    assert hashlib.sha256(data).hexdigest() == pack["sha256"], f"wrong checksum: {name}"
    db = sqlite3.connect(":memory:")
    db.deserialize(gzip.decompress(data))
    return db


def build_packs(folder, pack_folder):
    os.makedirs(pack_folder, exist_ok=True)
    packs = {}
    for lang, read in LANGUAGES.items():
        # The meaning packs come first: their words feed the accent rows of the lemma pack.
        data, headwords = {}, set()
        for pair in (pair for pair in PAIRS if pair.startswith(f"{lang}-")):
            rows = meanings(read_only(f"{folder}/{pair}.sqlite3"), pair)
            headwords.update(row[1] for row in rows)
            data[f"meaning-{pair}"] = make_pack(pack_folder, f"meaning-{pair}", MEANING, rows)
        lemmas = keep_phrase_rows(read(lang, folder))
        extra = VARIANTS[lang](lang, headwords, folder) if lang in VARIANTS else set()
        # Some entries have the rest of a template in the text: `-ο}`, `}}`.
        lemma_rows = sorted(row for row in set(lemmas) | set(accent_lemmas(lang, lemmas, headwords)) | extra if not re.search("[{}]", row[1] + row[2]))
        data = {f"lemma-{lang}": make_pack(pack_folder, f"lemma-{lang}", LEMMA, lemma_rows), **data}
        bundle, offset = f"bundle-{lang}.bin", 0
        with open(f"{pack_folder}/{bundle}", "wb") as out:
            for name, pack in data.items():
                out.write(pack)
                packs[name] = {"file": bundle, "offset": offset, "size": len(pack), "sha256": hashlib.sha256(pack).hexdigest()}
                offset += len(pack)
    manifest = {"format": FORMAT, "packs": packs}
    json.dump(manifest, open(f"{pack_folder}/packs.json", "w"), indent=2, sort_keys=True)
    check_packs(pack_folder, manifest)
    for lang in LANGUAGES:
        print(f"bundle-{lang}.bin: {os.path.getsize(f'{pack_folder}/bundle-{lang}.bin') / 1024 / 1024:.1f} MB")


def check_packs(pack_folder, manifest):
    """Stops with an error if a pack is wrong."""
    def count(name, sql):
        return open_pack(pack_folder, manifest, name).execute(sql).fetchone()[0]
    # (pack, column 1, column 2): each row must exist. `meaning` rows are (word, translation), `lemma` rows are (form, lemma).
    expected = [
        ("meaning-en-es", "house", "casa"), ("meaning-fr-en", "maison", "house"), ("meaning-ru-en", "дом", "house"),
        ("meaning-de-en", "haus", "house"), ("meaning-pt-en", "casa", "house"), ("meaning-zh-en", "你好", "hello"),
        ("lemma-en", "houses", "house"), ("lemma-en", "walked", "walk"), ("lemma-en", "ran", "run"), ("lemma-en", "was", "be"),
        ("lemma-en", "went", "go"), ("lemma-en", "gave up", "give up"),
        ("lemma-es", "casas", "casa"), ("lemma-fr", "maisons", "maison"),
        ("lemma-fr", "mangeons", "manger"), ("lemma-fr", "suis", "être"), ("lemma-fr", "allé", "aller"), ("lemma-fr", "belles", "belle"),
        ("lemma-ru", "столы", "стол"), ("lemma-ru", "шёл", "идти"), ("lemma-de", "häuser", "haus"), ("lemma-de", "ging", "gehen"),
        ("lemma-de", "gegangen", "gehen"), ("lemma-pt", "casas", "casa"), ("lemma-pt", "falou", "falar"),
        # Words without accents map to the real word. Simplified and Traditional Chinese map to each other.
        ("meaning-it-en", "casa", "house"), ("meaning-nl-en", "huis", "house"), ("meaning-pl-en", "dom", "house"), ("meaning-tr-en", "ev", "house"),
        ("lemma-it", "case", "casa"), ("lemma-it", "andò", "andare"), ("lemma-nl", "huizen", "huis"), ("lemma-nl", "ging", "gaan"),
        ("lemma-pl", "domy", "dom"), ("lemma-pl", "poszedł", "pójść"), ("lemma-tr", "evler", "ev"), ("lemma-tr", "gitti", "gitmek"),
        ("lemma-pl", "lodz", "łódź"), ("lemma-tr", "kiz", "kız"), ("lemma-tr", "cok", "çok"), ("lemma-it", "perche", "perché"),
        ("lemma-es", "todavia", "todavía"), ("lemma-es", "esta", "estar"), ("lemma-fr", "cafe", "café"), ("lemma-fr", "mange", "manger"),
        ("lemma-ru", "еж", "ёж"), ("lemma-de", "uber", "über"),
        ("lemma-zh", "汉字", "漢字"), ("lemma-zh", "電腦", "电脑"), ("lemma-zh", "中国", "中國"),
        # Round 3: one word and one inflected or unaccented form for each new language. The Japanese form is a verb.
        ("meaning-bg-en", "дом", "house"), ("lemma-bg", "къщи", "къща"), ("meaning-ca-en", "casa", "house"), ("lemma-ca", "estic", "estar"),
        ("meaning-cs-en", "dům", "house"), ("lemma-cs", "domy", "dům"), ("lemma-cs", "dum", "dům"), ("meaning-da-en", "hus", "house"),
        ("lemma-da", "huse", "hus"), ("lemma-da", "ol", "øl"), ("meaning-el-en", "σπίτι", "house"), ("lemma-el", "σπίτια", "σπίτι"),
        ("lemma-el", "σπιτι", "σπίτι"), ("meaning-fi-en", "talo", "house"), ("lemma-fi", "talot", "talo"), ("lemma-fi", "talossa", "talo"),
        ("meaning-ga-en", "teach", "house"), ("lemma-ga", "tithe", "teach"), ("lemma-ga", "bad", "bád"), ("meaning-id-en", "rumah", "home"),
        ("lemma-id", "dimakan", "makan"), ("meaning-ja-en", "いえ", "house"), ("lemma-ja", "食べた", "食べる"), ("meaning-ku-en", "xanî", "house"),
        ("lemma-ku", "askan", "ask"), ("meaning-la-en", "domus", "house"), ("lemma-la", "domum", "domus"), ("lemma-la", "gratis", "grātīs"),
        ("meaning-lt-en", "namas", "house"), ("lemma-lt", "namai", "namas"), ("meaning-mg-en", "trano", "house"), ("meaning-no-en", "hus", "house"),
        ("lemma-no", "husene", "hus"), ("meaning-sv-en", "hus", "house"), ("lemma-sv", "husen", "hus"), ("lemma-sv", "ar", "år"),
        ("meaning-en-fi", "house", "talo"), ("meaning-en-ja", "house", "家"), ("meaning-en-el", "house", "σπίτι"),
    ]
    for name, first, second in expected:
        columns = "word = ? and translation = ?" if name.startswith("meaning") else "form = ? and lemma = ?"
        table = name.split("-")[0]
        assert open_pack(pack_folder, manifest, name).execute(f"select count(*) from {table} where {columns}", (first, second)).fetchone()[0] == 1, (name, first, second)
    # Rows that must not exist: a tense in several words, a stress mark, and the Russian й folded to и.
    assert plain("йод") == "йод" and plain("ёж") == "еж" and plain("über") == "uber" and plain("łódź") == "lodz" and plain("kız") == "kiz"
    assert count("lemma-en", "select count(*) from lemma where form = 'most woodenly'") == 0
    assert count("lemma-nl", "select count(*) from lemma where form = 'no-table-tags'") == 0
    assert count("lemma-de", "select count(*) from lemma where form like '% %' and lemma not like '% %'") == 0
    # The Japanese `か` and `が` are two syllables. Finnish forms with a possessive ending are not in the pack.
    assert count("lemma-ja", "select count(*) from lemma where (form = 'か' and lemma = 'が') or (form = 'が' and lemma = 'か')") == 0
    assert count("lemma-fi", "select count(*) from lemma where form = 'talossani'") == 0
    assert count("lemma-ru", "select count(*) from lemma where lemma like '%' || char(769) || '%' or form like '%' || char(769) || '%'") == 0
    for name in manifest["packs"]:
        table = name.split("-")[0]
        # Some pairs are small, because the WikDict file is small: Indonesian to Irish has 13 rows. Chinese has no base forms, only the rows between the two scripts.
        assert count(name, f"select count(*) from {table}") > (100 if table == "lemma" else 0), name
        if table == "meaning":
            assert count(name, "select count(*) from (select 1 from meaning group by word, translation having count(*) > 1)") == 0, name
        else:
            assert count(name, "select count(*) from (select 1 from lemma group by form, lemma having count(*) > 1)") == 0, name
            assert count(name, "select count(*) from lemma where (form || lemma) glob '*[{}]*'") == 0, name  # the rest of a template
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
    db.execute(DICTIONARY_LEMMA)
    # Read by the runner to know the installed languages. A scan of `meaning` would take 10 ms.
    db.execute("create table language(code text)")
    db.executemany("insert into language values (?)", [(lang,) for lang in langs])
    for name in names:
        table = name.split("-")[0]
        rows = open_pack(pack_folder, manifest, name).execute(f"select * from {table}")
        db.executemany(f"insert into {table} values ({','.join('?' * len(rows.description))})", rows)
    db.execute("create index meaning_idx on meaning(direction, word)")
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
    elif len(args) == 2 and args[0] == "check":
        check_packs(args[1], json.load(open(f"{args[1]}/packs.json")))
    elif len(args) >= 4 and args[0] == "merge":
        merge(args[1], args[2], args[3:])
    else:
        sys.exit(__doc__)
