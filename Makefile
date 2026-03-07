# ============================================================
#  LexAudit — Project Makefile
#  Usage:  make help
# ============================================================

.PHONY: help install build test serve ui deploy clean lint docker docker-up docker-down wasm check

PYTHON   ?= python3
PIP      ?= pip
NPM      ?= npm
PYTEST   ?= $(PYTHON) -m pytest
UVICORN  ?= $(PYTHON) -m uvicorn

# Colours
GREEN  := \033[0;32m
YELLOW := \033[0;33m
CYAN   := \033[0;36m
RESET  := \033[0m

help: ## Show this help
	@echo "$(CYAN)LexAudit$(RESET) — AI Legal Contract Review with On-Chain Audit Trail\n"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  $(GREEN)%-18s$(RESET) %s\n", $$1, $$2}'
	@echo ""

# ─── Install ──────────────────────────────────────────────
install: ## Install all Python + Node dependencies
	@echo "$(YELLOW)→ Installing Python dependencies...$(RESET)"
	$(PIP) install -r requirements.txt
	@echo "$(YELLOW)→ Installing Weilchain SDK...$(RESET)"
	$(PIP) install ../wadk-sdk/adk/python/weil_wallet ../wadk-sdk/adk/python/weil_ai 2>/dev/null || true
	@echo "$(YELLOW)→ Installing UI dependencies...$(RESET)"
	cd ui && $(NPM) install
	@echo "$(GREEN)✓ All dependencies installed$(RESET)"

install-python: ## Install Python deps only
	$(PIP) install -r requirements.txt
	$(PIP) install ../wadk-sdk/adk/python/weil_wallet ../wadk-sdk/adk/python/weil_ai 2>/dev/null || true

install-ui: ## Install Next.js UI deps only
	cd ui && $(NPM) install

# ─── Build ────────────────────────────────────────────────
wasm: ## Build Rust WASM applets
	@echo "$(YELLOW)→ Building WASM applets...$(RESET)"
	cd rust_applets && ./build.sh
	@echo "$(GREEN)✓ WASM built → src/applets/wasm/$(RESET)"

build: wasm ## Build everything (WASM + UI)
	@echo "$(YELLOW)→ Building Next.js UI...$(RESET)"
	cd ui && $(NPM) run build
	@echo "$(GREEN)✓ Full build complete$(RESET)"

# ─── Test ─────────────────────────────────────────────────
test: ## Run all tests
	$(PYTEST) tests/ -v

test-quick: ## Run tests (no verbose)
	$(PYTEST) tests/

lint: ## Run type checking
	$(PYTHON) -m pyright src/ 2>/dev/null || $(PYTHON) -m mypy src/ --ignore-missing-imports

# ─── Run ──────────────────────────────────────────────────
serve: ## Start FastAPI server (port 8000)
	@echo "$(CYAN)→ Starting LexAudit API on http://localhost:8000$(RESET)"
	$(PYTHON) server.py

ui: ## Start Next.js UI dev server (port 3000)
	@echo "$(CYAN)→ Starting LexAudit UI on http://localhost:3000$(RESET)"
	cd ui && $(NPM) run dev

dev: ## Start both API + UI (background API, foreground UI)
	@echo "$(CYAN)→ Starting API server in background...$(RESET)"
	$(PYTHON) server.py &
	@sleep 2
	@echo "$(CYAN)→ Starting UI...$(RESET)"
	cd ui && $(NPM) run dev

# ─── CLI ──────────────────────────────────────────────────
demo: ## Run demo analysis on sample contract
	$(PYTHON) main.py --input contracts/sample_nda.txt --format json --no-human-gate

demo-offline: ## Run offline demo (no API keys needed) — uses local fallback MCP client
	@echo "$(CYAN)→ Running offline demo with local fallback client...$(RESET)"
	$(PYTHON) -c "\
import json; from pathlib import Path; \
from src.agent.control_loop import run_lexaudit; \
from src.config import Settings; \
from src.tools.router import ToolRouter, ToolSpec; \
from src.tools.local_fallback import LocalFallbackMCPClient; \
ct = Path('contracts/sample_nda.txt').read_text(); \
s = Settings(anthropic_api_key='', runs_dir=Path('.runs'), enforce_mcp=True, max_retries=1, retry_backoff_seconds=0.0, weilchain_wallet_path='private_key.wc', weilchain_node_url='https://sentinel.unweil.me'); \
specs = {'clause_extractor': ToolSpec(applet_id='aaaaaar6cc2arozt4ycprttocyc62p6sqwuyecuuqzjgdanbdiupplimxa', interface='ClauseExtractor', default_method='extract_clauses'), 'risk_scorer': ToolSpec(applet_id='aaaaaawmbew7e54girflltyb3ox76oyylr4f4tduu2unmzlmjyhnkhe5ba', interface='RiskScorer', default_method='score_clause_risk')}; \
client = LocalFallbackMCPClient(tool_specs=specs); \
router = ToolRouter(settings=s, mcp_client=client); \
r = run_lexaudit(contract_text=ct, filename='sample_nda.txt', settings=s, router=router, human_gate_enabled=True, decision_provider=None); \
Path('demo_output').mkdir(exist_ok=True); \
Path('demo_output/demo_result.json').write_text(json.dumps(r.to_dict(), indent=2)); \
print(f'✓ {len(r.state.clauses)} clauses, {len(r.state.risk_results)} risks, {len(r.audit_log)} audit events'); \
[print(f'  [{x.risk_level.value:6}] {x.clause_title}') for x in r.state.risk_results]; \
print(f'→ demo_output/demo_result.json')"

# ─── Deploy ───────────────────────────────────────────────
deploy: wasm ## Build WASM and deploy applets to Weilchain
	@echo "$(YELLOW)→ Deploying applets to Weilchain...$(RESET)"
	node scripts/deploy_applets.mjs
	@echo "$(GREEN)✓ Applets deployed — update .env with new IDs$(RESET)"

# ─── Docker ───────────────────────────────────────────────
docker: ## Build Docker images
	docker compose build

docker-up: ## Start with Docker Compose
	docker compose up -d
	@echo "$(GREEN)✓ API: http://localhost:8000  UI: http://localhost:3000$(RESET)"

docker-down: ## Stop Docker Compose
	docker compose down

# ─── Check / Verify ──────────────────────────────────────
check: ## Verify environment and deployed applets
	@echo "$(CYAN)Checking environment...$(RESET)"
	@$(PYTHON) -c "from dotenv import load_dotenv; load_dotenv(); from src.config import load_settings; s = load_settings(); \
		llm = 'groq' if s.use_groq and s.groq_api_key else 'gemini' if s.use_gemini and s.gemini_api_key else 'openai' if s.use_openai and s.openai_api_key else 'anthropic' if s.anthropic_api_key else 'none'; \
		print('  LLM provider:     ', llm, '✓' if llm != 'none' else '✗'); \
		print('  Weilchain node:   ', s.weilchain_node_url or '✗'); \
		print('  ClauseExtractor:  ', s.clause_extractor_applet_id[:20]+'...' if s.clause_extractor_applet_id else '✗'); \
		print('  RiskScorer:       ', s.risk_scorer_applet_id[:20]+'...' if s.risk_scorer_applet_id else '✗'); \
		print('  Wallet:           ', '✓' if __import__('pathlib').Path(s.weilchain_wallet_path).exists() else '✗')"
	@echo "$(CYAN)Checking server...$(RESET)"
	@curl -sf http://localhost:8000/api/health 2>/dev/null | $(PYTHON) -m json.tool || echo "  Server not running"

health: ## Quick health check
	@curl -sf http://localhost:8000/api/health | $(PYTHON) -m json.tool

# ─── Clean ────────────────────────────────────────────────
clean: ## Remove build artifacts and caches
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .runs/*.jsonl .runs/*/
	rm -rf rust_applets/target
	@echo "$(GREEN)✓ Cleaned$(RESET)"

clean-all: clean ## Deep clean (includes node_modules, WASM)
	rm -rf node_modules ui/node_modules
	rm -rf src/applets/wasm/*.wasm
	rm -rf ui/.next
	@echo "$(GREEN)✓ Deep cleaned$(RESET)"
