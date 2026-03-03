use serde::{Deserialize, Serialize};
use weil_macros::{WeilType, constructor, query, smart_contract};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RiskFlag {
    pub code: String,
    pub description: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Clause {
    pub id: u32,
    pub title: String,
    pub text: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RiskScore {
    pub clause_id: u32,
    pub clause_title: String,
    pub risk_level: String,
    pub confidence: String,
    pub reason: String,
    pub flags: Vec<RiskFlag>,
}

trait RiskScorer {
    fn new() -> Result<Self, String> where Self: Sized;
    async fn score_clause_risk(&self, clause_id: u32, clause_title: String, clause_text: String) -> Result<RiskScore, String>;
    async fn score_all_clauses(&self, contract_text: String) -> Result<Vec<RiskScore>, String>;
}

#[derive(Serialize, Deserialize, WeilType)]
pub struct RiskScorerState {}

const HIGH_KEYWORDS: &[(&str, &str)] = &[
    ("unlimited", "UNLIMITED_OBLIGATION"),
    ("irrevocable", "IRREVOCABLE_TERM"),
    ("worldwide", "WORLDWIDE_SCOPE"),
    ("no liability", "NO_LIABILITY_RECOURSE"),
    ("perpetual", "PERPETUAL_TERM"),
    ("waive all", "WAIVER_OF_RIGHTS"),
];

const MEDIUM_KEYWORDS: &[(&str, &str)] = &[
    ("penalty", "PENALTY_CLAUSE"),
    ("indemnify", "INDEMNITY_OBLIGATION"),
    ("exclusive", "EXCLUSIVITY_RESTRICTION"),
    ("non-compete", "NON_COMPETE_RESTRICTION"),
    ("confidential", "CONFIDENTIALITY_CONSTRAINT"),
    ("automatic renewal", "AUTO_RENEWAL_RISK"),
    ("termination fee", "TERMINATION_FEE"),
];

fn score_single(clause_id: u32, clause_title: String, clause_text: String) -> RiskScore {
    let lower = clause_text.to_lowercase();
    let mut flags: Vec<RiskFlag> = Vec::new();
    let mut high_count = 0u32;
    let mut medium_count = 0u32;

    for &(kw, code) in HIGH_KEYWORDS {
        if lower.contains(kw) {
            high_count += 1;
            flags.push(RiskFlag { code: code.to_string(), description: format!("Contains '{}'", kw) });
        }
    }
    for &(kw, code) in MEDIUM_KEYWORDS {
        if lower.contains(kw) {
            medium_count += 1;
            flags.push(RiskFlag { code: code.to_string(), description: format!("Contains '{}'", kw) });
        }
    }

    let (risk_level, confidence) = if high_count >= 2 {
        ("HIGH", "0.90")
    } else if high_count == 1 {
        ("HIGH", "0.75")
    } else if medium_count >= 2 {
        ("MEDIUM", "0.80")
    } else if medium_count == 1 {
        ("MEDIUM", "0.65")
    } else {
        ("LOW", "0.85")
    };

    let reason = if flags.is_empty() {
        "No significant risk indicators detected".to_string()
    } else {
        format!("Found {} risk indicator(s): {}", flags.len(),
            flags.iter().map(|f| f.code.clone()).collect::<Vec<_>>().join(", "))
    };

    RiskScore {
        clause_id,
        clause_title,
        risk_level: risk_level.to_string(),
        confidence: confidence.to_string(),
        reason,
        flags,
    }
}

fn is_clause_header(line: &str) -> bool {
    let trimmed = line.trim();
    if trimmed.is_empty() { return false; }
    let mut chars = trimmed.chars().peekable();
    let mut has_digit = false;
    while let Some(ch) = chars.peek().copied() {
        if ch.is_ascii_digit() { has_digit = true; chars.next(); } else { break; }
    }
    if !has_digit { return false; }
    matches!(chars.peek().copied(), Some('.') | Some(')') | Some(':'))
}

#[smart_contract]
impl RiskScorer for RiskScorerState {
    #[constructor]
    fn new() -> Result<Self, String> where Self: Sized {
        Ok(RiskScorerState {})
    }

    #[query]
    async fn score_clause_risk(&self, clause_id: u32, clause_title: String, clause_text: String) -> Result<RiskScore, String> {
        if clause_text.trim().is_empty() {
            return Err("clause_text cannot be empty".to_string());
        }
        Ok(score_single(clause_id, clause_title, clause_text))
    }

    #[query]
    async fn score_all_clauses(&self, contract_text: String) -> Result<Vec<RiskScore>, String> {
        if contract_text.trim().is_empty() {
            return Err("contract_text cannot be empty".to_string());
        }
        // Simple clause splitting for batch scoring
        let mut results: Vec<RiskScore> = Vec::new();
        let mut cur_id = 0u32;
        let mut cur_title = String::new();
        let mut cur_body: Vec<String> = Vec::new();

        let flush = |results: &mut Vec<RiskScore>, id: u32, title: &str, body: &Vec<String>| {
            if id > 0 && !body.is_empty() {
                let text = body.join("\n").trim().to_string();
                if !text.is_empty() {
                    results.push(score_single(id, title.to_string(), text));
                }
            }
        };

        for line in contract_text.lines() {
            if is_clause_header(line) {
                flush(&mut results, cur_id, &cur_title, &cur_body);
                cur_id += 1;
                cur_title = line.trim().to_string();
                cur_body.clear();
            } else if cur_id > 0 {
                cur_body.push(line.to_string());
            }
        }
        flush(&mut results, cur_id, &cur_title, &cur_body);

        if results.is_empty() && !contract_text.trim().is_empty() {
            results.push(score_single(1, "Full Contract".to_string(), contract_text));
        }
        Ok(results)
    }
}
