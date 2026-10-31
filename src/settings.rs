// The settings file (main and second language) and the paths of the files that the program uses.
use std::{
    collections::BTreeSet,
    fs, io,
    path::{Path, PathBuf},
};

/// The target of a query without language markers. See `lookup`.
#[derive(Clone, Debug, PartialEq)]
pub struct Settings {
    pub main: String,
    pub second: String,
}

impl Default for Settings {
    fn default() -> Self {
        Settings { main: "en".into(), second: "es".into() }
    }
}

fn base_dir(variable: &str, fallback: &str) -> PathBuf {
    match std::env::var_os(variable) {
        Some(dir) if !dir.is_empty() => PathBuf::from(dir),
        _ => PathBuf::from(std::env::var_os("HOME").unwrap_or_default()).join(fallback),
    }
}

pub fn config_path() -> PathBuf {
    base_dir("XDG_CONFIG_HOME", ".config").join("krunner-translate/config.ini")
}

pub fn dictionary_path() -> PathBuf {
    base_dir("XDG_DATA_HOME", ".local/share").join("krunner-translate/dictionary.sqlite3")
}

impl Settings {
    /// A missing file, a missing key or a bad line gives the default value.
    pub fn load(path: &Path) -> Settings {
        let mut settings = Settings::default();
        for line in fs::read_to_string(path).unwrap_or_default().lines() {
            let Some((key, value)) = line.split_once('=') else { continue };
            let value = value.trim();
            if value.is_empty() {
                continue;
            }
            match key.trim() {
                "main" => settings.main = value.to_string(),
                "second" => settings.second = value.to_string(),
                _ => {}
            }
        }
        settings
    }

    /// Writes a temporary file and renames it, so a reader never sees half a file.
    pub fn save(&self, path: &Path) -> io::Result<()> {
        fs::create_dir_all(path.parent().unwrap_or(Path::new(".")))?;
        let temp = path.with_extension("ini.tmp");
        fs::write(&temp, format!("main={}\nsecond={}\n", self.main, self.second))?;
        fs::rename(temp, path)
    }

    /// Sets `main` or `second` to an installed language. The two languages never match: the other one takes the old value.
    /// Returns the line to print. Nothing changes on an error.
    pub fn set(&mut self, which: &str, code: &str, installed: &BTreeSet<String>) -> Result<String, String> {
        let (label, this, other) = match which {
            "main" => ("Main", &mut self.main, &mut self.second),
            "second" => ("Second", &mut self.second, &mut self.main),
            _ => return Err("Use main or second.".into()),
        };
        if !installed.contains(code) {
            return Err(format!("Language {code} is not installed."));
        }
        if this == code {
            return Ok(format!("{label} language is already {code}."));
        }
        let swapped = other == code;
        if swapped {
            *other = this.clone();
        }
        *this = code.to_string();
        let mut message = format!("Main language: {}\nSecond language: {}", self.main, self.second);
        if swapped {
            message.push_str("\nSwapped the main and second languages.");
        }
        Ok(message)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn languages(codes: &[&str]) -> BTreeSet<String> {
        codes.iter().map(|code| code.to_string()).collect()
    }

    fn settings(main: &str, second: &str) -> Settings {
        Settings { main: main.into(), second: second.into() }
    }

    #[test]
    fn load_and_save() {
        let folder = std::env::temp_dir().join(format!("krunner-translate-test-{}", std::process::id()));
        let path = folder.join("config.ini");
        // No file, a file with bad lines, and a file with one key: the default fills the gaps.
        assert_eq!(Settings::load(&path), Settings::default());
        fs::create_dir_all(&folder).unwrap();
        fs::write(&path, "garbage\n# comment\nmain = fr \nsecond=\nother=x\n").unwrap();
        assert_eq!(Settings::load(&path), settings("fr", "es"));
        // Save, then load.
        settings("es", "fr").save(&path).unwrap();
        assert_eq!(Settings::load(&path), settings("es", "fr"));
        assert!(!path.with_extension("ini.tmp").exists());
        fs::remove_dir_all(&folder).unwrap();
        // Save creates the folder.
        settings("de", "it").save(&folder.join("new/config.ini")).unwrap();
        assert_eq!(Settings::load(&folder.join("new/config.ini")), settings("de", "it"));
        fs::remove_dir_all(&folder).unwrap();
    }

    #[test]
    fn set_rules() {
        let installed = languages(&["en", "es", "fr"]);
        let mut s = settings("en", "es");
        assert_eq!(s.set("main", "fr", &installed).unwrap(), "Main language: fr\nSecond language: es");
        assert_eq!(s, settings("fr", "es"));
        // The other language takes the old value.
        let swapped = "\nSwapped the main and second languages.";
        assert_eq!(s.set("main", "es", &installed).unwrap(), format!("Main language: es\nSecond language: fr{swapped}"));
        assert_eq!(s, settings("es", "fr"));
        assert_eq!(s.set("second", "es", &installed).unwrap(), format!("Main language: fr\nSecond language: es{swapped}"));
        assert_eq!(s, settings("fr", "es"));
        // Errors change nothing.
        assert_eq!(s.set("main", "fr", &installed).unwrap(), "Main language is already fr.");
        assert_eq!(s.set("main", "de", &installed).unwrap_err(), "Language de is not installed.");
        assert_eq!(s.set("third", "en", &installed).unwrap_err(), "Use main or second.");
        assert_eq!(s, settings("fr", "es"));
    }
}
