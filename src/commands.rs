// The commands of the program, for example `krunner-translate list`. A call with no argument is the KRunner runner (see main.rs).
use crate::{
    lookup::installed_languages,
    settings::{Settings, config_path, dictionary_path},
};
use rusqlite::{Connection, OpenFlags};
use std::{collections::BTreeSet, process::ExitCode};

const USAGE: &str = "Usage: krunner-translate list | set main|second <code>";

pub fn run(args: &[String]) -> ExitCode {
    let args: Vec<&str> = args.iter().map(String::as_str).collect();
    let result = match args.as_slice() {
        ["list"] => list(),
        ["set", which, code] => set(which, code),
        _ => {
            eprintln!("{USAGE}");
            return ExitCode::from(2);
        }
    };
    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(message) => {
            eprintln!("{message}");
            ExitCode::FAILURE
        }
    }
}

fn installed() -> Result<BTreeSet<String>, String> {
    let path = dictionary_path();
    let db = Connection::open_with_flags(&path, OpenFlags::SQLITE_OPEN_READ_ONLY)
        .map_err(|error| format!("Cannot open the dictionary {}: {error}", path.display()))?;
    installed_languages(&db).map_err(|error| error.to_string())
}

fn list() -> Result<(), String> {
    let installed = installed()?;
    let settings = Settings::load(&config_path());
    println!("Settings file: {}", config_path().display());
    println!("Main language: {}", settings.main);
    println!("Second language: {}", settings.second);
    println!("Installed languages: {}", installed.into_iter().collect::<Vec<_>>().join(" "));
    Ok(())
}

fn set(which: &str, code: &str) -> Result<(), String> {
    let path = config_path();
    let mut settings = Settings::load(&path);
    let before = settings.clone();
    let message = settings.set(which, code, &installed()?)?;
    if settings != before {
        settings.save(&path).map_err(|error| format!("Cannot write {}: {error}", path.display()))?;
    }
    println!("{message}");
    Ok(())
}
