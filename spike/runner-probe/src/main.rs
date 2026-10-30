// Throwaway KRunner D-Bus probe. Logs every call to /tmp/krunner-probe.log. Not part of the plugin.
// `tr N` returns N rows. A query with the word "slow" waits 300 ms inside Match.
// Round 2: `tr t<Type>` sets the Type, `tr two` returns two sections, `tr w...` drops stale calls.
use std::{
    collections::HashMap,
    io::Write,
    process::Command,
    sync::atomic::{AtomicU64, Ordering},
    time::Duration,
};
use zbus::{connection, interface, Connection, OwnedVariant, Variant};

const LOG: &str = "/tmp/krunner-probe.log";
// If this file exists, the probe stays alive after Teardown.
const STAY_ALIVE: &str = "/tmp/krunner-probe-stay";

type Row = (String, String, String, i32, f64, HashMap<String, OwnedVariant>);

fn log(event: &str) {
    let ms = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_millis();
    let mut file = std::fs::OpenOptions::new().create(true).append(true).open(LOG).unwrap();
    writeln!(file, "{ms} pid={} {event}", std::process::id()).unwrap();
}

fn value<'a>(v: impl Into<Variant<'a>>) -> OwnedVariant {
    OwnedVariant::try_from(v.into()).unwrap()
}

// Number of the newest Match call. A waiting call compares its own number with this one.
static LATEST_CALL: AtomicU64 = AtomicU64::new(0);

// `count` rows named "<label> 1", "<label> 2", ... in one section.
fn make_rows(category: &str, label: &str, count: usize, type_: i32) -> Vec<Row> {
    (1..=count)
        .map(|i| {
            let mut props = HashMap::new();
            props.insert("subtext".to_string(), value(format!("probe word, score {}", 100 - i)));
            props.insert("category".to_string(), value(category));
            props.insert("actions".to_string(), value(Variant::new(vec!["wlcopy".to_string()])));
            (
                format!("{label}-{i}"),
                format!("{label} {i}"),
                "accessories-dictionary".to_string(),
                type_,
                1.0 - i as f64 / 1000.0,
                props,
            )
        })
        .collect()
}

struct Runner;

#[interface(name = "org.kde.krunner1")]
impl Runner {
    // The D-Bus method is named Match. `match` is a Rust keyword, so the Rust name differs.
    #[zbus(name = "Match")]
    async fn match_query(&self, query: &str) -> Vec<Row> {
        let call = LATEST_CALL.fetch_add(1, Ordering::SeqCst) + 1;
        log(&format!("Match start #{call} {query:?}"));
        // The word after the trigger decides which test runs.
        let arg = query.split_whitespace().nth(1).unwrap_or("");
        let rows = if let Some(kind) = arg.strip_prefix('t').and_then(|n| n.parse::<i32>().ok()) {
            // `tr t50`: 3 rows with Type 50. Finds which Type puts the section at the top.
            make_rows("Translation", &format!("type{kind}"), 3, kind)
        } else if arg == "two" {
            // `tr two`: two sections with 8 rows each.
            let mut rows = make_rows("Section A", "A", 8, 100);
            rows.extend(make_rows("Section B", "B", 8, 100));
            rows
        } else if arg.starts_with('w') {
            // `tr wait`: only the newest call returns rows. Older calls return an empty list.
            async_io::Timer::after(Duration::from_millis(300)).await;
            if LATEST_CALL.load(Ordering::SeqCst) != call {
                log(&format!("Match stale #{call} {query:?}"));
                return Vec::new();
            }
            make_rows("Translation", "wait", 3, 100)
        } else {
            if query.contains("slow") {
                async_io::Timer::after(Duration::from_millis(300)).await;
            }
            let n = query.split_whitespace().last().and_then(|w| w.parse::<usize>().ok()).unwrap_or(12);
            make_rows("Translation", "meaning", n, 100)
        };
        log(&format!("Match end #{call} {query:?} rows={}", rows.len()));
        rows
    }

    fn actions(&self) -> Vec<(String, String, String)> {
        log("Actions");
        vec![("wlcopy".into(), "Copy with wl-copy".into(), "edit-copy".into())]
    }

    // An empty action id is the default action (Enter): copy through Klipper.
    async fn run(&self, #[zbus(connection)] conn: &Connection, match_id: &str, action_id: &str) {
        log(&format!("Run id={match_id:?} action={action_id:?}"));
        let text = match_id.replace('-', " ");
        if action_id == "wlcopy" {
            match Command::new("wl-copy").arg(&text).spawn() {
                Ok(_) => log("wl-copy started"),
                Err(e) => log(&format!("wl-copy error {e}")),
            }
        } else {
            let reply = conn
                .call_method(Some("org.kde.klipper"), "/klipper", Some("org.kde.klipper.klipper"), "setClipboardContents", &(text.as_str(),))
                .await;
            log(&format!("klipper reply {:?}", reply.map(|_| "ok")));
        }
    }

    fn teardown(&self) {
        log("Teardown");
        if !std::path::Path::new(STAY_ALIVE).exists() {
            // Exit after a short delay so that the D-Bus reply can leave first.
            std::thread::spawn(|| {
                std::thread::sleep(Duration::from_millis(300));
                log("exit after Teardown");
                std::process::exit(0);
            });
        }
    }

    // DBus2 runners: KRunner calls this to learn the trigger word.
    fn config(&self) -> HashMap<String, OwnedVariant> {
        log("Config");
        let mut config = HashMap::new();
        config.insert("TriggerWords".to_string(), value(Variant::new(vec!["tr".to_string()])));
        config.insert("MinLetterCount".to_string(), value(1i32));
        config
    }

    fn set_activation_token(&self, token: &str) {
        log(&format!("SetActivationToken len={}", token.len()));
    }
}

fn main() {
    log("start");
    // The connection runs on zbus's own helper thread, so the main thread only waits.
    let _conn = zbus::block_on(
        connection::Builder::session()
            .name("net.krunnertranslate.probe")
            .serve_at("/runner", Runner)
            .build(),
    )
    .expect("connect to the session bus");
    loop {
        std::thread::park();
    }
}
