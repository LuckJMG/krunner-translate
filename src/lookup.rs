// Finds translations for a parsed query in dictionary.sqlite3 (tables `meaning` and `lemma`, see tools/build_dictionary.py).
use crate::parser::Query;
use rusqlite::Connection;
use std::collections::BTreeSet;

// Fixed for now. A settings file comes later.
const MAIN: &str = "en";
const SECOND: &str = "es";

pub struct Row {
    pub translation: String,
    pub sense: String,
    pub score: f64,
}

/// One direction and one word (the text itself or one of its base forms), for example `casa (es → en)`.
pub struct Section {
    pub heading: String,
    pub rows: Vec<Row>,
}

pub enum Outcome {
    Sections(Vec<Section>),
    /// A language of the query has no data in the file.
    MissingLanguage(String),
    NotFound,
}

pub fn lookup(db: &Connection, query: &Query) -> rusqlite::Result<Outcome> {
    let installed = installed_languages(db)?;
    for code in [&query.from, &query.to].into_iter().flatten() {
        if !installed.contains(code) {
            return Ok(Outcome::MissingLanguage(code.clone()));
        }
    }
    // Directions in the order of their sections. Without `from:`, Spanish to English comes first (English is the main language).
    let directions: Vec<(String, String)> = match (&query.from, &query.to) {
        (Some(from), Some(to)) => vec![(from.clone(), to.clone())],
        (Some(from), None) => vec![(from.clone(), (if from == MAIN { SECOND } else { MAIN }).to_string())],
        (None, Some(to)) => installed.iter().filter(|lang| *lang != to).map(|lang| (lang.clone(), to.clone())).collect(),
        (None, None) => vec![(SECOND.to_string(), MAIN.to_string()), (MAIN.to_string(), SECOND.to_string())],
    };
    let word = query.text.to_lowercase();
    let mut sections = Vec::new();
    for (from, to) in &directions {
        sections.extend(direction_sections(db, from, to, &word)?);
    }
    Ok(if sections.is_empty() { Outcome::NotFound } else { Outcome::Sections(sections) })
}

/// The languages in the `direction` column (`en-es` gives `en` and `es`).
fn installed_languages(db: &Connection) -> rusqlite::Result<BTreeSet<String>> {
    let mut statement = db.prepare("select distinct direction from meaning")?;
    let directions = statement.query_map([], |row| row.get::<_, String>(0))?;
    let mut languages = BTreeSet::new();
    for direction in directions {
        let direction = direction?;
        if let Some((from, to)) = direction.split_once('-') {
            languages.insert(from.to_string());
            languages.insert(to.to_string());
        }
    }
    Ok(languages)
}

/// The sections of one direction, the best score first. The word itself comes before its base forms if scores are equal.
fn direction_sections(db: &Connection, from: &str, to: &str, word: &str) -> rusqlite::Result<Vec<Section>> {
    let mut words = vec![word.to_string()];
    let mut statement = db.prepare("select lemma from lemma where lang = ?1 and form = ?2")?;
    for lemma in statement.query_map([from, word], |row| row.get::<_, String>(0))? {
        words.push(lemma?);
    }
    let mut sections = Vec::new();
    for word in words {
        let rows = rows(db, &format!("{from}-{to}"), &word)?;
        if !rows.is_empty() {
            sections.push(Section { heading: format!("{word} ({from} → {to})"), rows });
        }
    }
    sections.sort_by(|a, b| b.rows[0].score.total_cmp(&a.rows[0].score));
    Ok(sections)
}

/// The rows of one word in one direction, the best score first.
fn rows(db: &Connection, direction: &str, word: &str) -> rusqlite::Result<Vec<Row>> {
    let mut statement = db.prepare(
        "select translation, sense, score from meaning where direction = ?1 and word = ?2 order by score desc, translation",
    )?;
    let rows = statement.query_map([direction, word], |row| {
        Ok(Row { translation: row.get(0)?, sense: row.get(1)?, score: row.get(2)? })
    })?;
    rows.collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::parser::parse;

    fn test_db() -> Connection {
        let db = Connection::open_in_memory().unwrap();
        db.execute_batch(
            "create table meaning(direction text, word text, translation text, sense text, score real);
             create table lemma(lang text, form text, lemma text);
             insert into meaning values
               ('en-es', 'house', 'casa', '', 256.1),
               ('en-es', 'house', 'cámara', 'debating chamber', 112.5),
               ('es-en', 'casa', 'house', '', 200),
               ('es-en', 'casa', 'home', '', 150),
               ('es-en', 'casar', 'marry', '', 100),
               ('en-es', 'pan', 'sartén', '', 90),
               ('es-en', 'pan', 'bread', '', 80);
             insert into lemma values ('es', 'casas', 'casar'), ('es', 'casas', 'casa');",
        )
        .unwrap();
        db
    }

    /// The headings and the translations of the first section for a query text.
    fn run(text: &str) -> (Vec<String>, Vec<String>) {
        match lookup(&test_db(), &parse(text).unwrap()).unwrap() {
            Outcome::Sections(sections) => (
                sections.iter().map(|s| s.heading.clone()).collect(),
                sections[0].rows.iter().map(|r| r.translation.clone()).collect(),
            ),
            Outcome::MissingLanguage(code) => (vec![format!("missing {code}")], vec![]),
            Outcome::NotFound => (vec!["not found".to_string()], vec![]),
        }
    }

    #[test]
    fn lookup_rules() {
        // Found in both directions: Spanish to English first.
        assert_eq!(run("tr pan").0, ["pan (es → en)", "pan (en → es)"]);
        // Two base forms: the better score first. Case does not matter.
        assert_eq!(run("tr Casas").0, ["casa (es → en)", "casar (es → en)"]);
        // Rows by score.
        assert_eq!(run("tr house").1, ["casa", "cámara"]);
        // From one language only, and to one language only.
        assert_eq!(run("tr en: house").0, ["house (en → es)"]);
        assert_eq!(run("tr :es house").0, ["house (en → es)"]);
        assert_eq!(run("tr es:en pan").0, ["pan (es → en)"]);
        // A language without data, a pair without data, a word without data.
        assert_eq!(run("tr fr: house").0, ["missing fr"]);
        assert_eq!(run("tr en:en house").0, ["not found"]);
        assert_eq!(run("tr zzzxq").0, ["not found"]);
    }
}
