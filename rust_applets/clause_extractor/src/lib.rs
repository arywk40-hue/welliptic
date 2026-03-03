use serde::{Deserialize, Serialize};
use weil_macros::{WeilType, constructor, query, smart_contract};

/// Clause record matching the WIDL `record Clause`
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Clause {
    pub id: u32,
    pub title: String,
    pub text: String,
}

trait ClauseExtractor {
    fn new() -> Result<Self, String> where Self: Sized;
    async fn extract_clauses(&self, contract_text: String) -> Result<Vec<Clause>, String>;
    async fn count_clauses(&self, contract_text: String) -> Result<u32, String>;
}

#[derive(Serialize, Deserialize, WeilType)]
pub struct ClauseExtractorState {}

fn is_clause_header(line: &str) -> bool {
    let trimmed = line.trim();
    if trimmed.is_empty() { return false; }
    if let Some(rest) = trimmed.strip_prefix('§') {
        let mut has_digit = false;
        for ch in rest.chars() {
            if ch.is_ascii_digit() { has_digit = true; continue; }
            return has_digit && (ch == '.' || ch == ')' || ch.is_whitespace());
        }
    }
    let mut chars = trimmed.chars().peekable();
    let mut has_digit = false;
    while let Some(ch) = chars.peek().copied() {
        if ch.is_ascii_digit() { has_digit = true; chars.next(); } else { break; }
    }
    if !has_digit { return false; }
    matches!(chars.peek().copied(), Some('.') | Some(')') | Some(':'))
}

fn parse_header_id(header: &str, fallback: u32) -> u32 {
    let trimmed = header.trim();
    let mut digits = String::new();
    for ch in trimmed.chars() {
        if ch == '§' { continue; }
        if ch.is_ascii_digit() { digits.push(ch); continue; }
        if !digits.is_empty() { break; }
        if !ch.is_whitespace() { break; }
    }
    digits.parse::<u32>().unwrap_or(fallback)
}

fn parse_header_title(header: &str) -> String {
    let trimmed = header.trim();
    let mut iter = trimmed.chars().peekable();
    if matches!(iter.peek(), Some('§')) { iter.next(); }
    while let Some(ch) = iter.peek().copied() {
        if ch.is_ascii_digit() { iter.next(); } else { break; }
    }
    while let Some(ch) = iter.peek().copied() {
        if matches!(ch, '.' | ')' | ':' | '-' | ' ' | '\t') { iter.next(); } else { break; }
    }
    let title: String = iter.collect();
    let title = title.trim();
    if title.is_empty() { "Untitled Clause".to_string() } else { title.to_string() }
}

fn split_contract(text: &str) -> Vec<Clause> {
    let mut clauses: Vec<Clause> = Vec::new();
    let mut cur_header: Option<String> = None;
    let mut cur_body: Vec<String> = Vec::new();
    let flush = |clauses: &mut Vec<Clause>, header: &Option<String>, body: &Vec<String>| {
        if let Some(h) = header {
            let next_id = (clauses.len() as u32) + 1;
            let id = parse_header_id(h, next_id);
            let title = parse_header_title(h);
            let text = body.join("\n").trim().to_string();
            if !text.is_empty() { clauses.push(Clause { id, title, text }); }
        }
    };
    for line in text.lines() {
        if is_clause_header(line) {
            flush(&mut clauses, &cur_header, &cur_body);
            cur_header = Some(line.trim().to_string());
            cur_body.clear();
        } else if cur_header.is_some() {
            cur_body.push(line.to_string());
        }
    }
    flush(&mut clauses, &cur_header, &cur_body);
    if clauses.is_empty() && !text.trim().is_empty() {
        clauses.push(Clause { id: 1, title: "Full Contract".to_string(), text: text.trim().to_string() });
    }
    clauses
}

#[smart_contract]
impl ClauseExtractor for ClauseExtractorState {
    #[constructor]
    fn new() -> Result<Self, String> where Self: Sized {
        Ok(ClauseExtractorState {})
    }

    #[query]
    async fn extract_clauses(&self, contract_text: String) -> Result<Vec<Clause>, String> {
        if contract_text.trim().is_empty() {
            return Err("contract_text cannot be empty".to_string());
        }
        Ok(split_contract(&contract_text))
    }

    #[query]
    async fn count_clauses(&self, contract_text: String) -> Result<u32, String> {
        if contract_text.trim().is_empty() {
            return Err("contract_text cannot be empty".to_string());
        }
        Ok(split_contract(&contract_text).len() as u32)
    }
}
