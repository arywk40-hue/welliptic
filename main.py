# main.py
import os
from dotenv import load_dotenv
from src.agent.graph import build_graph

load_dotenv()

SAMPLE_CONTRACT = """
CONSULTING AGREEMENT

1. Services
Consultant agrees to provide software development services to Client.

2. Payment
Client shall pay Consultant $500/hour with no upper limit on total hours billed.
Invoices must be paid within 3 days or a 25% penalty applies.

3. Intellectual Property
All work product created by Consultant remains the exclusive property of Consultant.
Client receives a limited, revocable license only.

4. Non-Compete
Consultant shall not work for any company in any industry for 10 years
after termination of this agreement worldwide.

5. Liability
Client assumes full liability for any damages arising from use of deliverables.
Consultant liability is unlimited and survives contract termination.

6. Termination
Either party may terminate with 24 hours notice. No compensation owed on termination.
"""

def main():
    print("🏛️  LexAudit — AI Legal Contract Reviewer")
    print("=" * 50)

    graph = build_graph()

    initial_state = {
        "contract_text":        SAMPLE_CONTRACT,
        "filename":             "sample_consulting_agreement.txt",
        "clauses":              [],
        "current_clause_index": 0,
        "risk_results":         [],
        "step_index":           0,
        "max_steps":            50,
        "fatal_error":          False,
        "error_message":        None,
        "human_gate_open":      False,
        "human_decision":       None,
        "final_report":         None,
        "session_id":           None,
        "audit_log":            []
    }

    result = graph.invoke(initial_state)

    print("\n" + result["final_report"])
    print(f"\n📋 Full audit log: {len(result['audit_log'])} entries captured")

if __name__ == "__main__":
    main()
```

---

## ▶️ Step 6 — Add API Key & Run!

In your `.env` file:
```
ANTHROPIC_API_KEY=your_key_here