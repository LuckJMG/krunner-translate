// The commands of the program, for example `krunner-translate list`. A call with no argument is the KRunner runner (see main.rs).
use crate::{
    lookup::installed_languages,
    packs::{self, Manifest},
    settings::{Settings, config_path, dictionary_path},
};
use rusqlite::{Connection, OpenFlags};
use std::{
    collections::BTreeSet,
    io::{self, Write},
    process::ExitCode,
};

const USAGE: &str = "Usage:
  krunner-translate list                     Show the settings and the installed languages
  krunner-translate set main|second <code>   Set the main or the second language
  krunner-translate add [<code>]             List the available languages, or install one
  krunner-translate update <code>            Download an installed language again
  krunner-translate remove <code>            Remove an installed language
  krunner-translate help                     Show this text";

pub fn run(args: &[String]) -> ExitCode {
    let args: Vec<&str> = args.iter().map(String::as_str).collect();
    let result = match args.as_slice() {
        ["list"] => list(),
        ["set", which, code] => set(which, code),
        ["add"] => add(None),
        ["add", code] => add(Some(code)),
        ["update", code] => update(code),
        ["remove", code] => remove(code),
        ["help" | "--help" | "-h"] => {
            println!("{USAGE}");
            return ExitCode::SUCCESS;
        }
        _ => {
            eprintln!("Unknown command or wrong arguments: {}\n\n{USAGE}", args.join(" "));
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

fn open(flags: OpenFlags) -> Result<Connection, String> {
    let path = dictionary_path();
    Connection::open_with_flags(&path, flags).map_err(|error| format!("Cannot open the dictionary {}: {error}", path.display()))
}

fn installed() -> Result<BTreeSet<String>, String> {
    installed_languages(&open(OpenFlags::SQLITE_OPEN_READ_ONLY)?).map_err(|error| error.to_string())
}

/// Asks a yes or no question. Only `y` or `yes` means yes.
fn confirm(question: &str) -> Result<(), String> {
    print!("{question} [y/N] ");
    io::stdout().flush().map_err(|error| error.to_string())?;
    let mut answer = String::new();
    io::stdin().read_line(&mut answer).map_err(|error| error.to_string())?;
    match answer.trim().to_lowercase().as_str() {
        "y" | "yes" => Ok(()),
        _ => Err("Cancelled. Nothing changed.".into()),
    }
}

fn list() -> Result<(), String> {
    let installed = installed()?;
    let settings = Settings::load(&config_path());
    println!("Settings file: {}", config_path().display());
    println!("Main language: {}", settings.main);
    println!("Second language: {}", settings.second);
    println!("Installed languages:");
    for language in installed {
        println!("- {language}");
    }
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

/// With no code: lists the available languages. With a code: downloads and installs the language.
fn add(code: Option<&str>) -> Result<(), String> {
    let manifest = Manifest::fetch()?;
    let installed = installed()?;
    let available = manifest.languages();
    let Some(code) = code else {
        println!("Available languages:");
        for language in &available {
            println!("- {language}{}", if installed.contains(language) { " (installed)" } else { "" });
        }
        println!("\nAdd one with: krunner-translate add <code>");
        return Ok(());
    };
    if installed.contains(code) {
        return Err(format!("Language {code} is already installed."));
    }
    if !available.contains(code) {
        return Err(format!("Language {code} is not available. Run krunner-translate add to see the list."));
    }
    let names = packs::needed(code, &installed);
    let megabytes = manifest.size(&names)? as f64 / 1024.0 / 1024.0;
    confirm(&format!("Download {} packs ({megabytes:.1} MB) and add language {code}?", names.len()))?;
    let downloads = download_all(&manifest, names)?;
    packs::merge(&mut open(OpenFlags::SQLITE_OPEN_READ_WRITE)?, code, &downloads)?;
    println!("Added language {code}.");
    Ok(())
}

fn download_all(manifest: &Manifest, names: Vec<String>) -> Result<Vec<(String, Vec<u8>)>, String> {
    let mut downloads = Vec::new();
    for name in names {
        println!("Downloading {name}");
        downloads.push((name.clone(), manifest.download(&name)?));
    }
    Ok(downloads)
}

/// Downloads the packs of an installed language again and replaces its data. For example after a fix in the packs.
fn update(code: &str) -> Result<(), String> {
    let manifest = Manifest::fetch()?;
    let installed = installed()?;
    if !installed.contains(code) {
        return Err(format!("Language {code} is not installed."));
    }
    let names = packs::needed(code, &installed);
    let megabytes = manifest.size(&names)? as f64 / 1024.0 / 1024.0;
    confirm(&format!("Download {} packs ({megabytes:.1} MB) and replace the data of language {code}?", names.len()))?;
    let downloads = download_all(&manifest, names)?;
    packs::update(&mut open(OpenFlags::SQLITE_OPEN_READ_WRITE)?, code, &installed, &downloads)?;
    println!("Updated language {code}.");
    Ok(())
}

fn remove(code: &str) -> Result<(), String> {
    let installed = installed()?;
    if !installed.contains(code) {
        return Err(format!("Language {code} is not installed."));
    }
    let settings = Settings::load(&config_path());
    for (label, language) in [("main", &settings.main), ("second", &settings.second)] {
        if code == language {
            return Err(format!("Language {code} is the {label} language. Run krunner-translate set {label} <code> first."));
        }
    }
    confirm(&format!("Remove language {code} and its translations? You can add it again later."))?;
    packs::remove(&mut open(OpenFlags::SQLITE_OPEN_READ_WRITE)?, code, &installed)?;
    println!("Removed language {code}.");
    Ok(())
}
