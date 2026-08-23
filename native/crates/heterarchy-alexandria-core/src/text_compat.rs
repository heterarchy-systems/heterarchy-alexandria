//! Small Python text-semantics compatibility helpers shared by native compute modules.

/// Trim the exact Unicode whitespace set used by Python `str.strip`.
pub(crate) fn trim_python_whitespace(value: &str) -> &str {
    value.trim_matches(is_python_whitespace)
}

/// Collapse Python whitespace runs exactly like `" ".join(value.split())`.
pub(crate) fn collapse_python_whitespace(value: &str) -> String {
    let mut normalized = String::with_capacity(value.len());
    let mut pending_separator = false;
    for character in value.chars() {
        if is_python_whitespace(character) {
            pending_separator = !normalized.is_empty();
            continue;
        }
        if pending_separator {
            normalized.push(' ');
            pending_separator = false;
        }
        normalized.push(character);
    }
    normalized
}

/// Return whether a character belongs to Python's current `str.isspace` set.
pub(crate) fn is_python_whitespace(character: char) -> bool {
    matches!(
        character,
        '\u{0009}'..='\u{000D}'
            | '\u{001C}'..='\u{0020}'
            | '\u{0085}'
            | '\u{00A0}'
            | '\u{1680}'
            | '\u{2000}'..='\u{200A}'
            | '\u{2028}'
            | '\u{2029}'
            | '\u{202F}'
            | '\u{205F}'
            | '\u{3000}'
    )
}

#[cfg(test)]
mod tests {
    use super::{collapse_python_whitespace, trim_python_whitespace};

    #[test]
    fn matches_python_split_and_strip_whitespace_contracts() {
        let value = "\u{001c}\u{3000}alpha\t\nbeta\u{00a0}";
        assert_eq!(trim_python_whitespace(value), "alpha\t\nbeta");
        assert_eq!(collapse_python_whitespace(value), "alpha beta");
    }
}
