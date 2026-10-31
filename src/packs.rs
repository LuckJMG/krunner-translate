// Language packs: the list (packs.json), the download with its checks, and the merge into the dictionary.
// tools/build_packs.py makes the packs. A pack is a gzip file with one SQLite file inside.
use rusqlite::{Connection, MAIN_DB, Transaction, params_from_iter, types::Value};
use serde::Deserialize;
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    io::Read,
};

/// The data format that this program reads. See FORMAT in tools/build_packs.py.
const FORMAT: u32 = 2;
const DEFAULT_URL: &str = "https://github.com/LuckJMG/krunner-translate/releases/download/data-v2";
/// The size limit of `packs.json`. A larger answer is wrong.
const MAX_MANIFEST_BYTES: u64 = 100 * 1024 * 1024;

/// A pack is `size` bytes of the bundle `file`, from byte `offset`.
#[derive(Deserialize)]
struct Pack {
    file: String,
    offset: u64,
    size: u64,
    sha256: String,
}

#[derive(Deserialize)]
pub struct Manifest {
    format: u32,
    packs: BTreeMap<String, Pack>,
}

fn sql_error(error: rusqlite::Error) -> String {
    format!("Dictionary error: {error}")
}

/// Downloads one file of the release, or only the bytes of `range` (offset and size). `KRUNNER_TRANSLATE_PACKS_URL` replaces the address (for tests).
fn get(file: &str, range: Option<(u64, u64)>) -> Result<Vec<u8>, String> {
    let base = std::env::var("KRUNNER_TRANSLATE_PACKS_URL").unwrap_or_else(|_| DEFAULT_URL.to_string());
    let url = format!("{}/{file}", base.trim_end_matches('/'));
    let fail = |error: ureq::Error| format!("Cannot download {url}: {error}");
    let mut request = ureq::get(&url);
    let mut limit = MAX_MANIFEST_BYTES;
    if let Some((offset, size)) = range {
        request = request.header("Range", format!("bytes={offset}-{}", offset + size - 1));
        limit = size + 1; // ureq refuses a body that is exactly `limit` bytes long. `check` makes sure that the size is right.
    }
    let mut response = request.call().map_err(fail)?;
    // A server that ignores the range answers 200 with the whole bundle. That is too big to read here.
    if range.is_some() && response.status().as_u16() != 206 {
        return Err(format!("The server of {url} does not support byte ranges."));
    }
    response.body_mut().with_config().limit(limit).read_to_vec().map_err(fail)
}

/// The packs of a language: its base forms, and the pairs with every other installed language.
/// `add` needs them for a new language. `update` needs them again for an installed one.
pub fn needed(code: &str, installed: &BTreeSet<String>) -> Vec<String> {
    let mut names = vec![format!("lemma-{code}")];
    for other in installed.iter().filter(|other| *other != code) {
        names.push(format!("meaning-{code}-{other}"));
        names.push(format!("meaning-{other}-{code}"));
    }
    names
}

/// The packs of several languages. A pair pack that serves two of them is listed once.
pub fn needed_all(codes: &[String], installed: &BTreeSet<String>) -> Vec<String> {
    let mut names: Vec<String> = Vec::new();
    for name in codes.iter().flat_map(|code| needed(code, installed)) {
        if !names.contains(&name) {
            names.push(name);
        }
    }
    names
}

impl Manifest {
    pub fn fetch() -> Result<Manifest, String> {
        Manifest::parse(&get("packs.json", None)?)
    }

    fn parse(bytes: &[u8]) -> Result<Manifest, String> {
        let manifest: Manifest = serde_json::from_slice(bytes).map_err(|error| format!("Cannot read packs.json: {error}"))?;
        if manifest.format != FORMAT {
            return Err("This program cannot read these packs. Update the program.".into());
        }
        Ok(manifest)
    }

    /// The languages that have a base-form pack.
    pub fn languages(&self) -> BTreeSet<String> {
        self.packs.keys().filter_map(|name| name.strip_prefix("lemma-")).map(String::from).collect()
    }

    fn pack(&self, name: &str) -> Result<&Pack, String> {
        self.packs.get(name).ok_or_else(|| format!("The packs do not offer {name}."))
    }

    /// The download size of the packs, in bytes.
    pub fn size(&self, names: &[String]) -> Result<u64, String> {
        names.iter().map(|name| self.pack(name).map(|pack| pack.size)).sum()
    }

    /// Downloads one pack and checks its size and its SHA-256.
    pub fn download(&self, name: &str) -> Result<Vec<u8>, String> {
        let pack = self.pack(name)?;
        let data = get(&pack.file, Some((pack.offset, pack.size)))?;
        check(name, pack, &data)?;
        Ok(data)
    }
}

fn check(name: &str, pack: &Pack, data: &[u8]) -> Result<(), String> {
    let sha256: String = Sha256::digest(data).iter().map(|byte| format!("{byte:02x}")).collect();
    if data.len() as u64 != pack.size || sha256 != pack.sha256 {
        return Err(format!("The download of {name} is wrong (size or SHA-256). Nothing changed."));
    }
    Ok(())
}

/// Copies the rows of the packs into the dictionary.
fn insert_packs(tx: &Transaction, packs: &[(String, Vec<u8>)]) -> Result<(), String> {
    for (name, data) in packs {
        let table = match name.split('-').next() {
            Some("meaning") => "meaning",
            Some("lemma") => "lemma",
            _ => return Err(format!("Unknown pack: {name}")),
        };
        let mut sqlite = Vec::new();
        flate2::read::GzDecoder::new(&data[..])
            .read_to_end(&mut sqlite)
            .map_err(|error| format!("Cannot unpack {name}: {error}"))?;
        let mut pack = Connection::open_in_memory().map_err(sql_error)?;
        pack.deserialize_read_exact(MAIN_DB, &sqlite[..], sqlite.len(), true).map_err(sql_error)?;
        let mut select = pack.prepare(&format!("select * from {table}")).map_err(sql_error)?;
        let columns = select.column_count();
        let mut insert = tx
            .prepare(&format!("insert into {table} values ({})", vec!["?"; columns].join(",")))
            .map_err(sql_error)?;
        let mut rows = select.query([]).map_err(sql_error)?;
        while let Some(row) = rows.next().map_err(sql_error)? {
            let values = (0..columns).map(|i| row.get::<_, Value>(i)).collect::<Result<Vec<_>, _>>().map_err(sql_error)?;
            insert.execute(params_from_iter(values)).map_err(sql_error)?;
        }
    }
    Ok(())
}

/// Adds the language `code` with its packs. One transaction: if a pack is wrong, nothing changes.
pub fn merge(db: &mut Connection, code: &str, packs: &[(String, Vec<u8>)]) -> Result<(), String> {
    let tx = db.transaction().map_err(sql_error)?;
    insert_packs(&tx, packs)?;
    tx.execute("insert into language values (?1)", [code]).map_err(sql_error)?;
    tx.commit().map_err(sql_error)
}

/// Replaces the rows of the installed languages `codes` with the rows of fresh packs. One transaction: if a pack is wrong, nothing changes.
pub fn update(db: &mut Connection, codes: &[String], installed: &BTreeSet<String>, packs: &[(String, Vec<u8>)]) -> Result<(), String> {
    let tx = db.transaction().map_err(sql_error)?;
    for code in codes {
        delete_rows(&tx, code, installed)?;
    }
    insert_packs(&tx, packs)?;
    tx.commit().map_err(sql_error)
}

/// Deletes the pairs of `code` with the other installed languages and its base forms. The language row stays.
fn delete_rows(tx: &Transaction, code: &str, installed: &BTreeSet<String>) -> Result<(), String> {
    for other in installed.iter().filter(|other| *other != code) {
        tx.execute(
            "delete from meaning where direction = ?1 or direction = ?2",
            [format!("{code}-{other}"), format!("{other}-{code}")],
        )
        .map_err(sql_error)?;
    }
    tx.execute("delete from lemma where lang = ?1", [code]).map_err(sql_error)?;
    Ok(())
}

/// Removes the language `code`. The file keeps its size (no vacuum).
pub fn remove(db: &mut Connection, code: &str, installed: &BTreeSet<String>) -> Result<(), String> {
    let tx = db.transaction().map_err(sql_error)?;
    delete_rows(&tx, code, installed)?;
    tx.execute("delete from language where code = ?1", [code]).map_err(sql_error)?;
    tx.commit().map_err(sql_error)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    fn languages(codes: &[&str]) -> BTreeSet<String> {
        codes.iter().map(|code| code.to_string()).collect()
    }

    /// A pack: the SQL builds the SQLite file, then it is zipped.
    fn pack(sql: &str) -> Vec<u8> {
        let mut db = Connection::open_in_memory().unwrap();
        db.execute_batch(sql).unwrap();
        let mut gzip = flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::fast());
        gzip.write_all(&db.serialize(MAIN_DB).unwrap()).unwrap();
        gzip.finish().unwrap()
    }

    fn dictionary() -> Connection {
        let db = Connection::open_in_memory().unwrap();
        db.execute_batch(
            "create table meaning(direction text, word text, translation text, sense text, score real);
             create table lemma(lang text, form text, lemma text);
             create table language(code text);
             insert into language values ('en'), ('es');
             insert into meaning values ('en-es', 'house', 'casa', '', 1.5);
             insert into lemma values ('es', 'casas', 'casa');",
        )
        .unwrap();
        db
    }

    fn count(db: &Connection, sql: &str) -> i64 {
        db.query_row(sql, [], |row| row.get(0)).unwrap()
    }

    #[test]
    fn manifest_and_names() {
        let json = r#"{"format": 2, "packs": {
            "lemma-fr": {"file": "bundle-fr.bin", "offset": 0, "size": 3, "sha256": "x"},
            "lemma-en": {"file": "bundle-en.bin", "offset": 0, "size": 4, "sha256": "y"}}}"#;
        let manifest = Manifest::parse(json.as_bytes()).unwrap();
        assert_eq!(manifest.languages(), languages(&["en", "fr"]));
        assert_eq!(manifest.size(&["lemma-fr".into(), "lemma-en".into()]).unwrap(), 7);
        assert_eq!(manifest.size(&["lemma-de".into()]).unwrap_err(), "The packs do not offer lemma-de.");
        assert!(Manifest::parse(json.replace("\"format\": 2", "\"format\": 1").as_bytes()).is_err());
        assert!(Manifest::parse(b"nonsense").is_err());
        assert_eq!(
            needed("fr", &languages(&["en", "es"])),
            ["lemma-fr", "meaning-fr-en", "meaning-en-fr", "meaning-fr-es", "meaning-es-fr"]
        );
        // An installed language is not paired with itself.
        assert_eq!(needed("fr", &languages(&["en", "fr"])), ["lemma-fr", "meaning-fr-en", "meaning-en-fr"]);
        let both = ["en".to_string(), "fr".to_string()];
        assert_eq!(needed_all(&both, &languages(&["en", "fr"])), ["lemma-en", "meaning-en-fr", "meaning-fr-en", "lemma-fr"]);
        // The SHA-256 of "abc".
        let abc = Pack { file: String::new(), offset: 0, size: 3, sha256: "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad".into() };
        assert!(check("p", &abc, b"abc").is_ok());
        assert!(check("p", &abc, b"abd").is_err());
        assert!(check("p", &abc, b"abcd").is_err());
    }

    #[test]
    fn merge_and_remove() {
        let mut db = dictionary();
        let lemma = pack("create table lemma(lang text, form text, lemma text); insert into lemma values ('fr', 'maisons', 'maison');");
        let meaning = pack(
            "create table meaning(direction text, word text, translation text, sense text, score real);
             insert into meaning values ('fr-en', 'maison', 'house', 'a building', 90.5), ('fr-en', 'chat', 'cat', '', 80);",
        );
        // A wrong pack at the end: nothing changes.
        let bad = [("lemma-fr".to_string(), lemma.clone()), ("meaning-fr-en".to_string(), meaning.clone()), ("lemma-xx".to_string(), b"bad".to_vec())];
        assert!(merge(&mut db, "fr", &bad).is_err());
        assert_eq!(count(&db, "select count(*) from meaning") + count(&db, "select count(*) from lemma"), 2);
        assert_eq!(count(&db, "select count(*) from language where code = 'fr'"), 0);
        // Good packs: rows and the language row, with the right types.
        merge(&mut db, "fr", &bad[..2]).unwrap();
        assert_eq!(count(&db, "select count(*) from meaning where direction = 'fr-en'"), 2);
        assert_eq!(count(&db, "select count(*) from lemma where lang = 'fr'"), 1);
        assert_eq!(count(&db, "select count(*) from language where code = 'fr'"), 1);
        assert_eq!(count(&db, "select count(*) from meaning where translation = 'house' and sense = 'a building' and score = 90.5"), 1);
        // Remove: the pairs and base forms of fr go, the rest stays.
        remove(&mut db, "fr", &languages(&["en", "es", "fr"])).unwrap();
        assert_eq!(count(&db, "select count(*) from meaning"), 1);
        assert_eq!(count(&db, "select count(*) from lemma"), 1);
        assert_eq!(count(&db, "select count(*) from language"), 2);
    }

    #[test]
    fn update_replaces_one_language() {
        let mut db = dictionary();
        db.execute_batch(
            "insert into language values ('fr');
             insert into meaning values ('fr-en', 'maison', 'old house', '', 1), ('en-fr', 'house', 'old maison', '', 1);
             insert into lemma values ('fr', 'maisons', 'old');",
        )
        .unwrap();
        let lemma = pack("create table lemma(lang text, form text, lemma text); insert into lemma values ('fr', 'mangeons', 'manger');");
        let meaning = pack(
            "create table meaning(direction text, word text, translation text, sense text, score real);
             insert into meaning values ('fr-en', 'maison', 'house', '', 2);",
        );
        let installed = languages(&["en", "es", "fr"]);
        // A wrong pack at the end: the old rows stay.
        let bad = [("lemma-fr".to_string(), lemma.clone()), ("meaning-fr-en".to_string(), meaning.clone()), ("lemma-xx".to_string(), b"bad".to_vec())];
        assert!(update(&mut db, &["fr".to_string()], &installed, &bad).is_err());
        assert_eq!(count(&db, "select count(*) from meaning where translation like 'old %'"), 2);
        assert_eq!(count(&db, "select count(*) from lemma where lemma = 'old'"), 1);
        // Good packs: the rows of fr are new, the rest and the language row stay.
        update(&mut db, &["fr".to_string()], &installed, &bad[..2]).unwrap();
        assert_eq!(count(&db, "select count(*) from meaning where translation like 'old %'"), 0);
        assert_eq!(count(&db, "select count(*) from meaning where direction = 'fr-en' and translation = 'house'"), 1);
        assert_eq!(count(&db, "select count(*) from lemma where lang = 'fr' and form = 'mangeons'"), 1);
        assert_eq!(count(&db, "select count(*) from lemma where lemma = 'old'"), 0);
        assert_eq!(count(&db, "select count(*) from meaning where direction = 'en-es'"), 1);
        assert_eq!(count(&db, "select count(*) from language where code = 'fr'"), 1);
        assert_eq!(count(&db, "select count(*) from language"), 3);
    }
}
