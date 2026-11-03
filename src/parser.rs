// Turns a KRunner query `tr [from:][:to] text` into languages and text.

// The 26 WikDict languages, and six languages that have pairs with English only. A two-letter code counts as a language only if it is on this list.
const KNOWN: [&str; 32] = [
    "ar", "bg", "ca", "cs", "da", "de", "el", "en", "es", "fi", "fr", "ga", "he", "hu", "id", "it", "ja", "ko", "ku", "la", "lt", "mg",
    "nl", "no", "pl", "pt", "ru", "sk", "sv", "tr", "uk", "zh",
];

#[derive(Debug, PartialEq)]
pub struct Query {
    pub from: Option<String>,
    pub to: Option<String>,
    pub text: String,
}

/// Returns `None` if the query is not ours or the text is empty.
pub fn parse(raw: &str) -> Option<Query> {
    let rest = raw.strip_prefix("tr")?;
    if !rest.starts_with(char::is_whitespace) {
        return None; // `trv house` is not our query
    }
    let mut words = rest.split_whitespace();
    let first = words.next()?;
    // Only the first word can be a language part. If it is not, it is text, and `\:` becomes `:`.
    let (from, to, mut text) = match language_part(first) {
        Some((from, to)) => (from, to, String::new()),
        None => (None, None, first.replace("\\:", ":")),
    };
    for word in words {
        if !text.is_empty() {
            text.push(' ');
        }
        text.push_str(word);
    }
    if text.is_empty() {
        return None;
    }
    Some(Query { from, to, text })
}

/// `es:` gives (from), `:es` gives (to), `en:es` gives both. Codes become lowercase.
fn language_part(word: &str) -> Option<(Option<String>, Option<String>)> {
    let word = word.to_lowercase();
    let (from, to) = word.split_once(':')?;
    let is_valid = |code: &str| code.is_empty() || KNOWN.contains(&code);
    if (from.is_empty() && to.is_empty()) || !is_valid(from) || !is_valid(to) {
        return None;
    }
    let code = |code: &str| (!code.is_empty()).then(|| code.to_string());
    Some((code(from), code(to)))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn query(from: Option<&str>, to: Option<&str>, text: &str) -> Option<Query> {
        Some(Query { from: from.map(String::from), to: to.map(String::from), text: text.to_string() })
    }

    #[test]
    fn grammar_table() {
        assert_eq!(parse("tr house"), query(None, None, "house"));
        assert_eq!(parse("tr es: casa"), query(Some("es"), None, "casa"));
        assert_eq!(parse("tr :es house"), query(None, Some("es"), "house"));
        assert_eq!(parse("tr en:es house"), query(Some("en"), Some("es"), "house"));
        assert_eq!(parse("tr EN:ES house"), query(Some("en"), Some("es"), "house"));
        assert_eq!(parse("tr en:en house"), query(Some("en"), Some("en"), "house"));
        assert_eq!(parse("tr no: problem"), query(Some("no"), None, "problem"));
        assert_eq!(parse("tr no\\: problem"), query(None, None, "no: problem"));
        assert_eq!(parse("tr thank   you"), query(None, None, "thank you"));
        assert_eq!(parse("tr xx: house"), query(None, None, "xx: house"));
        assert_eq!(parse("tr es:xx house"), query(None, None, "es:xx house"));
        assert_eq!(parse("tr : house"), query(None, None, ": house"));
        assert_eq!(parse("tr house es:"), query(None, None, "house es:"));
        for not_ours in ["tr", "tr ", "tr es:", "tr :es  ", "trv house", "house"] {
            assert_eq!(parse(not_ours), None, "{not_ours:?}");
        }
    }
}
