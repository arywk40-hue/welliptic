# LexAudit — WIDL Interface Reference

WIDL (Weilchain Interface Definition Language) defines the typed interfaces for LexAudit's on-chain WASM applets. The definitions live in `src/applets/*.widl` and are used to generate Rust bindings, validate MCP responses, and document the applet API.

---

## ClauseExtractor Interface

**File:** `src/applets/clause_extractor.widl`

```widl
record Clause {
    id: u32,
    title: string,
    text: string
}

@mcp
interface ClauseExtractor {
    // Extracts all distinct legal clauses from a contract text.
    query func extract_clauses(
        // full contract text to analyse
        contract_text: string
    ) -> result<list<Clause>, string>;

    // Returns number of clauses found in a contract without full extraction.
    query func count_clauses(
        contract_text: string
    ) -> result<u32, string>
}
```

### Types

#### `Clause`

| Field | Type | Description |
|-------|------|-------------|
| `id` | `u32` | 1-based clause identifier |
| `title` | `string` | Human-readable clause title (e.g. `"Confidentiality"`) |
| `text` | `string` | Full clause text as extracted from the contract |

### Methods

#### `extract_clauses(contract_text: string) -> Vec<Clause>`

Extracts all distinct legal clauses from the provided contract text. Returns a list of `Clause` records in document order. On error, returns an `Err(string)` with a description of the failure.

**Input:**
- `contract_text` — the full raw text of the contract to analyse

**Output:** `Vec<Clause>` — ordered list of extracted clauses

#### `count_clauses(contract_text: string) -> u32`

Returns the number of clauses found in a contract without performing full extraction. Useful for quick validation before committing to a full extraction call.

**Input:**
- `contract_text` — the full raw text of the contract

**Output:** `u32` — count of detected clauses

---

## RiskScorer Interface

**File:** `src/applets/risk_scorer.widl`

```widl
record RiskFlag {
    code: string,
    description: string
}

record Clause {
    id: u32,
    title: string,
    text: string
}

record RiskScore {
    clause_id: u32,
    clause_title: string,
    risk_level: string,
    confidence: string,
    reason: string,
    flags: list<RiskFlag>
}

@mcp
interface RiskScorer {
    // Scores a single legal clause for risk level (LOW, MEDIUM, HIGH).
    query func score_clause_risk(
        // the clause object to score
        clause_id: u32,
        clause_title: string,
        clause_text: string
    ) -> result<RiskScore, string>;

    // Scores all clauses in a batch and returns ordered results.
    query func score_all_clauses(
        contract_text: string
    ) -> result<list<RiskScore>, string>
}
```

### Types

#### `RiskFlag`

| Field | Type | Description |
|-------|------|-------------|
| `code` | `string` | Machine-readable flag code (e.g. `"WORLDWIDE_SCOPE"`) |
| `description` | `string` | Human-readable explanation of the flag |

#### `RiskScore`

| Field | Type | Description |
|-------|------|-------------|
| `clause_id` | `u32` | ID of the scored clause (matches `Clause.id`) |
| `clause_title` | `string` | Title of the scored clause |
| `risk_level` | `string` | One of `"LOW"`, `"MEDIUM"`, `"HIGH"` |
| `confidence` | `string` | Confidence score as a decimal string (e.g. `"0.85"`) — see note below |
| `reason` | `string` | Explanation of the risk assessment |
| `flags` | `list<RiskFlag>` | Specific risk indicators found in the clause |

#### `RiskLevel` (enum)

| Value | Meaning |
|-------|---------|
| `LOW` | No significant risk indicators; standard clause |
| `MEDIUM` | Moderate risk indicators requiring attention |
| `HIGH` | Severe risk indicators that typically require legal review |

> **Note on `confidence` as `string`:** The WIDL `confidence` field is typed as `string` rather than `f32` for serialization compatibility. Weilchain WASM applets written in Rust serialize `f32` values as strings to avoid JSON precision issues across the MCP boundary. Python parsers in `clause_extractor.py` and `risk_scorer.py` convert this string to `float` when constructing `RiskScore` dataclass instances.

### Methods

#### `score_clause_risk(clause_id: u32, clause_title: string, clause_text: string) -> RiskScore`

Scores a single legal clause for risk level. Examines the clause text for risk indicators (e.g. indefinite terms, worldwide scope, unlimited indemnity) and returns a `RiskScore` with level, confidence, reason, and flags.

**Input:**
- `clause_id` — numeric identifier matching the corresponding `Clause.id`
- `clause_title` — title of the clause being scored
- `clause_text` — full text of the clause to evaluate

**Output:** `RiskScore`

#### `score_all_clauses(contract_text: string) -> Vec<RiskScore>`

Scores all clauses in a contract in a single batch call. Internally performs extraction and scoring in one pass. Returns results in clause order.

**Input:**
- `contract_text` — the full raw text of the contract

**Output:** `Vec<RiskScore>` — ordered list of risk scores

---

## MCP Envelope Format

All Weilchain MCP applet responses are wrapped in a standard envelope:

```json
{
  "ok": true,
  "result": {
    "Ok": <T>
  }
}
```

On error:

```json
{
  "ok": false,
  "result": {
    "Err": "error message string"
  }
}
```

Where `<T>` is the WIDL return type serialized to JSON:
- `Vec<Clause>` → JSON array of clause objects
- `RiskScore` → JSON object with all `RiskScore` fields
- `u32` → JSON integer
- `Vec<RiskScore>` → JSON array of risk score objects

---

## Python Parsing: `_extract_payload()`

Both `clause_extractor.py` and `risk_scorer.py` implement an `_extract_payload()` helper that:

1. Checks `response["ok"]` — raises or returns an error `ToolResult` on `false`
2. Navigates `response["result"]["Ok"]` to reach the typed payload
3. Validates field presence and types (e.g. `risk_level` must be `"LOW"`, `"MEDIUM"`, or `"HIGH"`)
4. Constructs the appropriate Python dataclass (`Clause`, `RiskScore`)

Example (from `risk_scorer.py`):

```python
def _extract_payload(response: dict) -> dict:
    if not response.get("ok"):
        raise ValueError(response.get("result", {}).get("Err", "unknown error"))
    return response["result"]["Ok"]
```

On parse failure (missing fields, invalid enum values, wrong types), the `ToolRouter` catches the exception and retries the call up to `LEXAUDIT_MAX_RETRIES` times. If all retries are exhausted, the pipeline terminates with `fatal_error = True`.

---

## Rust WASM Applet Implementation

The WASM applets are implemented in Rust (see `rust_applets/`) and compiled to WASM for deployment on Weilchain. Each applet:

1. Implements the WIDL interface using the Weilchain WASM SDK macros
2. Exports MCP-compatible entry points that accept JSON-encoded arguments
3. Returns results in the standard MCP envelope format
4. Handles all serialization internally, including `f32` → `string` for `confidence`

The compiled `.wasm` artifacts are stored in `src/applets/wasm/` and referenced by the `lexaudit.yaml` deployment manifest.

Deployment to Weilchain:

```bash
make deploy
# Sets CLAUSE_EXTRACTOR_APPLET_ID and RISK_SCORER_APPLET_ID in .env
```
