// Throwaway probe: connect to the session bus, open SQLite read-only, do one lookup, exit.
use rusqlite::{Connection, OpenFlags};

fn main() {
    let path = std::env::args().nth(1).expect("db path");
    let word = std::env::args().nth(2).expect("word");
    let _bus = pollster::block_on(zbus::Connection::session()).expect("session bus");
    let db = Connection::open_with_flags(path, OpenFlags::SQLITE_OPEN_READ_ONLY).expect("open db");
    let result: Option<String> = db
        .query_row("select trans_list from simple_translation where written_rep = ?1 limit 1", [word], |r| r.get(0))
        .ok();
    println!("{result:?}");
    let status = std::fs::read_to_string("/proc/self/status").unwrap();
    let hwm = status.lines().find(|l| l.starts_with("VmHWM")).unwrap();
    println!("{hwm}");
}
