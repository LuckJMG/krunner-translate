// KRunner D-Bus runner for `tr [from:][:to] text`. KRunner starts this program on demand, with no argument (see install/).
// A call with an argument runs a command instead (see commands.rs).
use krunner_translate::{
    commands,
    lookup::{Outcome, lookup},
    parser::parse,
    settings::{Settings, config_path, dictionary_path},
};
use rusqlite::{Connection as Db, OpenFlags};
use std::{
    collections::HashMap,
    process::{Command, ExitCode},
    sync::{
        Mutex,
        atomic::{AtomicU64, Ordering},
    },
    time::Duration,
};
use zbus::{Connection, OwnedVariant, Variant, connection, interface};

const EXIT_AFTER_RUN: Duration = Duration::from_secs(2);
const EXIT_AFTER_TEARDOWN: Duration = Duration::from_secs(5);
const SUBTEXT_MAX: usize = 80;
// KRunner calls Run 8 to 25 ms after Teardown, so the program must not exit at once.
// Match and Run count as activity and cancel a pending exit.
static ACTIVITY: AtomicU64 = AtomicU64::new(0);

type DbusRow = (String, String, String, i32, f64, HashMap<String, OwnedVariant>);

/// One row in the KRunner list.
struct MatchRow {
    /// `<section number>:<translation>`, or `none:` for a row that Enter does not copy.
    id: String,
    text: String,
    category: String,
    subtext: String,
    /// KRunner sorts sections by this number (0 to 100). Equal numbers have no defined order.
    kind: i32,
    relevance: f64,
}

fn status_row(text: &str, subtext: &str) -> MatchRow {
    MatchRow { id: "none:".into(), text: text.into(), category: "Translation".into(), subtext: subtext.into(), kind: 100, relevance: 1.0 }
}

fn build_rows(outcome: &Outcome) -> Vec<MatchRow> {
    match outcome {
        Outcome::Sections(sections) => sections
            .iter()
            .enumerate()
            .flat_map(|(s, section)| {
                // Sections arrive best score first. A lower number for each section keeps that order in KRunner.
                let kind = (100 - 2 * s as i32).max(0);
                section.rows.iter().enumerate().map(move |(i, row)| MatchRow {
                    id: format!("{s}:{}", row.translation),
                    text: row.translation.clone(),
                    category: section.heading.clone(),
                    subtext: cut(&row.sense),
                    kind,
                    relevance: 1.0 - i as f64 / 1000.0,
                })
            })
            .collect(),
        Outcome::MissingLanguage(code) => vec![status_row(&format!("Language {code} is not installed"), "See the README to add languages")],
        Outcome::NotFound => vec![status_row("No translation found", "")],
    }
}

fn cut(sense: &str) -> String {
    let sense = sense.split_whitespace().collect::<Vec<_>>().join(" ");
    if sense.chars().count() > SUBTEXT_MAX {
        sense.chars().take(SUBTEXT_MAX).collect::<String>() + "…"
    } else {
        sense
    }
}

fn value<'a>(v: impl Into<Variant<'a>>) -> OwnedVariant {
    OwnedVariant::try_from(v.into()).unwrap()
}

fn to_dbus(row: MatchRow) -> DbusRow {
    let mut props = HashMap::new();
    props.insert("category".to_string(), value(row.category));
    props.insert("subtext".to_string(), value(row.subtext));
    (row.id, row.text, "accessories-dictionary".to_string(), row.kind, row.relevance, props)
}

/// Exits after `delay`, unless a Match or Run call arrives before.
fn exit_later(delay: Duration) {
    let seen = ACTIVITY.load(Ordering::SeqCst);
    std::thread::spawn(move || {
        std::thread::sleep(delay);
        if ACTIVITY.load(Ordering::SeqCst) == seen {
            std::process::exit(0);
        }
    });
}

/// Klipper first. If it is not there (no Plasma), wl-copy.
async fn copy(conn: &Connection, text: &str) {
    let klipper = conn
        .call_method(Some("org.kde.klipper"), "/klipper", Some("org.kde.klipper.klipper"), "setClipboardContents", &(text,))
        .await;
    if klipper.is_err() {
        let _ = Command::new("wl-copy").args(["--", text]).spawn();
    }
}

struct Runner {
    /// `None` if the dictionary file did not open.
    db: Option<Mutex<Db>>,
    db_path: String,
}

#[interface(name = "org.kde.krunner1")]
impl Runner {
    // The D-Bus method is named Match. `match` is a Rust keyword, so the Rust name differs.
    #[zbus(name = "Match")]
    fn match_query(&self, query: &str) -> Vec<DbusRow> {
        ACTIVITY.fetch_add(1, Ordering::SeqCst);
        let Some(query) = parse(query) else { return Vec::new() };
        let Some(db) = &self.db else {
            return vec![to_dbus(status_row("Dictionary not found", &self.db_path))];
        };
        // Read on every call, so a `set` command works at once. The file is small.
        let rows = match lookup(&db.lock().unwrap(), &query, &Settings::load(&config_path())) {
            Ok(outcome) => build_rows(&outcome),
            Err(error) => vec![status_row("Dictionary error", &error.to_string())],
        };
        rows.into_iter().map(to_dbus).collect()
    }

    fn actions(&self) -> Vec<(String, String, String)> {
        Vec::new()
    }

    async fn run(&self, #[zbus(connection)] conn: &Connection, match_id: &str, _action_id: &str) {
        ACTIVITY.fetch_add(1, Ordering::SeqCst);
        if let Some((section, text)) = match_id.split_once(':')
            && section != "none"
        {
            copy(conn, text).await;
        }
        exit_later(EXIT_AFTER_RUN);
    }

    fn teardown(&self) {
        exit_later(EXIT_AFTER_TEARDOWN);
    }

    // DBus2 runners: KRunner calls this to learn the trigger word.
    fn config(&self) -> HashMap<String, OwnedVariant> {
        HashMap::from([("TriggerWords".to_string(), value(Variant::new(vec!["tr".to_string()])))])
    }

    fn set_activation_token(&self, _token: &str) {}
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if !args.is_empty() {
        return commands::run(&args);
    }
    let db_path = dictionary_path();
    let db = Db::open_with_flags(&db_path, OpenFlags::SQLITE_OPEN_READ_ONLY).ok().map(Mutex::new);
    // The connection runs on zbus's own helper thread, so the main thread only waits.
    let _conn = zbus::block_on(
        connection::Builder::session()
            .name("net.krunnertranslate.runner")
            .serve_at("/runner", Runner { db, db_path: db_path.display().to_string() })
            .build(),
    )
    .expect("connect to the session bus");
    loop {
        std::thread::park();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use krunner_translate::lookup::{Row, Section};

    fn row(translation: &str, sense: &str, score: f64) -> Row {
        Row { translation: translation.into(), sense: sense.into(), score }
    }

    #[test]
    fn rows_for_sections_and_status() {
        let outcome = Outcome::Sections(vec![
            Section { heading: "casa (es → en)".into(), rows: vec![row("home", &"x ".repeat(100), 9.0), row("house", "", 8.0)] },
            Section { heading: "casar (es → en)".into(), rows: vec![row("marry", "", 5.0)] },
        ]);
        let rows = build_rows(&outcome);
        assert_eq!(rows.iter().map(|r| r.id.as_str()).collect::<Vec<_>>(), ["0:home", "0:house", "1:marry"]);
        assert_eq!(rows.iter().map(|r| r.kind).collect::<Vec<_>>(), [100, 100, 98]);
        assert!(rows[0].relevance > rows[1].relevance);
        assert_eq!(rows[0].category, "casa (es → en)");
        assert_eq!(rows[0].subtext.chars().count(), SUBTEXT_MAX + 1); // 80 characters and "…"
        assert_eq!(rows[1].subtext, "");

        assert_eq!(build_rows(&Outcome::NotFound)[0].text, "No translation found");
        assert_eq!(build_rows(&Outcome::MissingLanguage("fr".into()))[0].text, "Language fr is not installed");
        assert_eq!(build_rows(&Outcome::NotFound)[0].id, "none:");
    }
}
