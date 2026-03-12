from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, cast

from src.agent.audit import AuditLogger, WeilAuditLogger, bounded_preview
from src.applets.clause_extractor import extract_clauses_from_payload
from src.applets.risk_scorer import score_clause_from_payload
from src.config import Settings
from src.tools.router import ToolExecutionError, ToolRouter
from src.types import AgentState, AuditResult, Clause, DecisionProvider, HumanDecision, RiskLevel, RiskScore, ToolContext


RISK_ORDER = {
    RiskLevel.LOW.value: 1,
    RiskLevel.MEDIUM.value: 2,
    RiskLevel.HIGH.value: 3,
}


def _normalize_text(text: str) -> str:
    return text.strip()


def _threshold_triggered(level: RiskLevel, threshold: str) -> bool:
    return RISK_ORDER[level.value] >= RISK_ORDER[threshold]


def _check_step_budget(state: AgentState, audit: AuditLogger) -> bool:
    if audit.step_index >= state.max_steps:
        state.fatal_error = True
        state.error_message = "MAX_STEPS_EXCEEDED"
        state.terminate_reason = "MAX_STEPS_EXCEEDED"
        return True
    return False


def _find_usage_block(value: Any, depth: int = 0) -> Optional[Dict[str, Any]]:
    if depth > 4:
        return None
    if isinstance(value, dict):
        for key in ("usage", "token_usage", "tokens"):
            candidate = value.get(key)
            if isinstance(candidate, dict):
                return candidate
        for nested in value.values():
            found = _find_usage_block(nested, depth + 1)
            if found is not None:
                return found
    if isinstance(value, list):
        for item in value[:10]:
            found = _find_usage_block(item, depth + 1)
            if found is not None:
                return found
    return None


def _to_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _extract_token_usage(raw: Any) -> Dict[str, Any]:
    usage = _find_usage_block(raw)
    if usage is None:
        return {}

    input_tokens = None
    for key in ("input_tokens", "prompt_tokens", "prompt_token_count"):
        input_tokens = _to_int(usage.get(key))
        if input_tokens is not None:
            break

    output_tokens = None
    for key in ("output_tokens", "completion_tokens", "completion_token_count"):
        output_tokens = _to_int(usage.get(key))
        if output_tokens is not None:
            break

    total_tokens = None
    for key in ("total_tokens", "total_token_count"):
        total_tokens = _to_int(usage.get(key))
        if total_tokens is not None:
            break

    normalized: Dict[str, Any] = {}
    if input_tokens is not None:
        normalized["input_tokens"] = input_tokens
    if output_tokens is not None:
        normalized["output_tokens"] = output_tokens
    if total_tokens is not None:
        normalized["total_tokens"] = total_tokens
    if normalized:
        normalized["raw"] = usage
    return normalized


def _emit_event(
    audit: AuditLogger,
    weil_audit: WeilAuditLogger,
    *,
    event_type: str,
    node: str,
    status: str = "ok",
    model: Optional[str] = None,
    tool_name: Optional[str] = None,
    input_payload: Optional[Any] = None,
    output_payload: Optional[Any] = None,
    error: Optional[str] = None,
    latency_ms: int = 0,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    event = audit.emit(
        event_type=event_type,
        node=node,
        status=status,
        model=model,
        tool_name=tool_name,
        input_payload=input_payload,
        output_payload=output_payload,
        error=error,
        latency_ms=latency_ms,
        metadata=metadata,
    )
    weil_audit.emit(
        event_type,
        {
            "node": node,
            "status": status,
            "model": model,
            "tool_name": tool_name,
            "input_hash": event.input_hash,
            "output_hash": event.output_hash,
            "latency_ms": latency_ms,
            "error": error,
            "metadata": metadata or {},
        },
    )
    # Attach the latest on-chain tx result back into the local audit event
    if weil_audit.tx_results:
        latest_tx = weil_audit.tx_results[-1]
        event.metadata["weilchain_tx_status"] = latest_tx.get("status")
        event.metadata["weilchain_batch_id"] = latest_tx.get("batch_id")
        event.metadata["weilchain_block_height"] = latest_tx.get("block_height")
        event.metadata["weilchain_tx_hash"] = latest_tx.get("tx_hash")


def _build_report(state: AgentState, pending_human_review: bool) -> Dict[str, Any]:
    high = [r for r in state.risk_results if r.risk_level == RiskLevel.HIGH]
    medium = [r for r in state.risk_results if r.risk_level == RiskLevel.MEDIUM]
    low = [r for r in state.risk_results if r.risk_level == RiskLevel.LOW]

    report_json = {
        "filename": state.filename,
        "decision": state.human_decision,
        "terminate_reason": state.terminate_reason,
        "pending_human_review": pending_human_review,
        "summary": {
            "high": len(high),
            "medium": len(medium),
            "low": len(low),
            "total_clauses": len(state.clauses),
        },
        "risk_results": [
            {
                "clause_id": result.clause_id,
                "clause_title": result.clause_title,
                "risk_level": result.risk_level.value,
                "confidence": result.confidence,
                "reason": result.reason,
                "flags": result.flags,
            }
            for result in state.risk_results
        ],
    }

    lines = [
        "LEXAUDIT CONTRACT RISK REPORT",
        f"File: {state.filename}",
        f"Decision: {state.human_decision}",
        f"Terminate reason: {state.terminate_reason}",
        f"Pending human review: {pending_human_review}",
        "",
        "Risk Summary:",
        f"- HIGH: {len(high)}",
        f"- MEDIUM: {len(medium)}",
        f"- LOW: {len(low)}",
        "",
    ]

    if high:
        lines.append("High-Risk Clauses:")
        for item in high:
            lines.append(f"- {item.clause_title}: {item.reason}")
        lines.append("")

    return {
        "report_json": report_json,
        "report_text": "\n".join(lines),
    }


def run_lexaudit(
    contract_text: str,
    filename: str,
    *,
    max_steps: int = 200,
    human_gate_threshold: str = RiskLevel.HIGH.value,
    settings: Optional[Settings] = None,
    router: Optional[ToolRouter] = None,
    human_gate_enabled: bool = True,
    decision_provider: Optional[DecisionProvider] = None,
) -> AuditResult:
    cfg = settings or Settings(anthropic_api_key="")
    if human_gate_threshold not in RISK_ORDER:
        raise ValueError("human_gate_threshold must be one of LOW, MEDIUM, HIGH")

    session_id = str(uuid.uuid4())
    audit = AuditLogger(cfg.runs_dir, session_id)
    weil_audit = WeilAuditLogger(cfg.weilchain_wallet_path, sentinel_host=cfg.weilchain_node_url)

    # Inject Weilchain signed auth headers into the MCP router so every
    # applet invocation is cryptographically authenticated via weil_middleware().
    if weil_audit.enabled and router is not None:
        auth_headers = weil_audit.get_auth_headers()
        if auth_headers:
            router._weil_auth_headers = auth_headers

    state = AgentState(
        contract_text=contract_text,
        filename=filename,
        max_steps=max_steps,
        session_id=session_id,
    )

    pending_human_review = False

    _emit_event(
        audit,
        weil_audit,
        event_type="INIT",
        node="control_loop",
        status="ok",
        metadata={"filename": filename, "max_steps": max_steps},
    )

    if _check_step_budget(state, audit):
        return _finalize_result(state, audit, weil_audit, pending_human_review)

    state.contract_text = _normalize_text(state.contract_text)
    _emit_event(
        audit,
        weil_audit,
        event_type="INGEST_START",
        node="ingest",
        status="ok",
        input_payload={"filename": filename},
    )

    if not state.contract_text:
        state.fatal_error = True
        state.error_message = "EMPTY_CONTRACT_TEXT"
        state.terminate_reason = "INVALID_INPUT"
        _emit_event(
            audit,
            weil_audit,
            event_type="INGEST_DONE",
            node="ingest",
            status="error",
            error=state.error_message,
        )
        return _finalize_result(state, audit, weil_audit, pending_human_review)

    _emit_event(
        audit,
        weil_audit,
        event_type="INGEST_DONE",
        node="ingest",
        status="ok",
        metadata={"chars": len(state.contract_text), "preview": bounded_preview(state.contract_text)},
    )

    if _check_step_budget(state, audit):
        return _finalize_result(state, audit, weil_audit, pending_human_review)

    if router is None:
        raise ToolExecutionError("ToolRouter is required for MCP execution")

    tool_ctx = ToolContext(
        session_id=session_id,
        model=cfg.anthropic_model,
        prompt_template_id="contract_clause_extract_v1",
    )

    clauses = _extract_clauses_with_retry(state, router, audit, weil_audit, tool_ctx)
    if clauses is None:
        return _finalize_result(state, audit, weil_audit, pending_human_review)

    state.clauses = clauses

    if _check_step_budget(state, audit):
        return _finalize_result(state, audit, weil_audit, pending_human_review)

    for clause in state.clauses:
        if _check_step_budget(state, audit):
            return _finalize_result(state, audit, weil_audit, pending_human_review)

        risk = _score_clause_with_retry(state, clause, router, audit, weil_audit, tool_ctx)
        if risk is None:
            return _finalize_result(state, audit, weil_audit, pending_human_review)

        state.risk_results.append(risk)
        state.current_clause_index += 1

    threshold_level = human_gate_threshold
    gated_items = [r for r in state.risk_results if _threshold_triggered(r.risk_level, threshold_level)]

    if human_gate_enabled and gated_items:
        state.human_gate_open = True
        _emit_event(
            audit,
            weil_audit,
            event_type="HUMAN_GATE_OPEN",
            node="human_gate",
            status="pending",
            metadata={
                "threshold": human_gate_threshold,
                "flagged_clause_ids": [r.clause_id for r in gated_items],
            },
        )

        if decision_provider is None:
            state.human_decision = "pending"
            state.terminate_reason = "HUMAN_REVIEW_PENDING"
            pending_human_review = True
            return _finalize_result(state, audit, weil_audit, pending_human_review)

        raw_decision = (decision_provider(gated_items) or "").strip().lower()
        if raw_decision not in {"approve", "reject"}:
            raw_decision = "reject"
            _emit_event(
                audit,
                weil_audit,
                event_type="HUMAN_DECISION_DEFAULTED",
                node="human_gate",
                status="error",
                error="Invalid human decision; defaulted to reject",
            )

        state.human_gate_open = False
        state.human_decision = cast(HumanDecision, raw_decision)
        _emit_event(
            audit,
            weil_audit,
            event_type="HUMAN_DECISION",
            node="human_gate",
            status="ok",
            metadata={"decision": raw_decision},
        )
    else:
        state.human_decision = "auto-approved"
        _emit_event(
            audit,
            weil_audit,
            event_type="HUMAN_DECISION",
            node="human_gate",
            status="ok",
            metadata={"decision": state.human_decision},
        )

    state.terminate_reason = "complete"
    return _finalize_result(state, audit, weil_audit, pending_human_review)


def _extract_clauses_with_retry(
    state: AgentState,
    router: ToolRouter,
    audit: AuditLogger,
    weil_audit: WeilAuditLogger,
    ctx: ToolContext,
) -> Optional[List[Clause]]:
    payload = {
        "_method": "extract_clauses",
        "contract_text": state.contract_text,
    }

    for parse_attempt in range(1, 3):
        predict_meta = {
            "parse_attempt": parse_attempt,
            "prompt_template_id": ctx.prompt_template_id,
            "predicted_method": "extract_clauses",
        }
        _emit_event(
            audit,
            weil_audit,
            event_type="TOOL_PREDICT",
            node="extract_clauses",
            status="ok",
            tool_name="clause_extractor",
            input_payload=payload,
            model=ctx.model,
            metadata=predict_meta,
        )

        result = router.execute_tool("clause_extractor", payload, ctx)
        exec_meta: Dict[str, Any] = {
            "attempts": result.attempts,
            "method": "extract_clauses",
            "prompt_template_id": ctx.prompt_template_id,
        }
        token_usage = _extract_token_usage(result.raw)
        if token_usage:
            exec_meta["token_usage"] = token_usage
        _emit_event(
            audit,
            weil_audit,
            event_type="TOOL_EXECUTE",
            node="extract_clauses",
            status="ok" if result.success else "error",
            tool_name="clause_extractor",
            input_payload=payload,
            output_payload=result.data,
            error=result.error,
            latency_ms=result.latency_ms,
            model=ctx.model,
            metadata=exec_meta,
        )

        if not result.success or not result.data:
            state.fatal_error = True
            state.error_message = result.error or "CLAUSE_EXTRACTION_TOOL_FAILED"
            state.terminate_reason = "TOOL_FAILURE"
            return None

        try:
            clauses = extract_clauses_from_payload(result.data)
            _emit_event(
                audit,
                weil_audit,
                event_type="CLAUSES_EXTRACTED",
                node="extract_clauses",
                status="ok",
                output_payload={"count": len(clauses)},
            )
            return clauses
        except Exception as exc:  # noqa: BLE001
            _emit_event(
                audit,
                weil_audit,
                event_type="CLAUSES_PARSE_ERROR",
                node="extract_clauses",
                status="error",
                error=str(exc),
                output_payload=result.data,
            )
            if parse_attempt == 2:
                state.fatal_error = True
                state.error_message = f"CLAUSE_PARSE_ERROR: {exc}"
                state.terminate_reason = "INVALID_TOOL_OUTPUT"
                return None
            payload = {
                "_method": "extract_clauses",
                "contract_text": state.contract_text,
            }

    return None


def _score_clause_with_retry(
    state: AgentState,
    clause: Clause,
    router: ToolRouter,
    audit: AuditLogger,
    weil_audit: WeilAuditLogger,
    ctx: ToolContext,
) -> Optional[RiskScore]:
    payload = {
        "_method": "score_clause_risk",
        "clause_id": clause.id,
        "clause_title": clause.title,
        "clause_text": clause.text,
    }

    for parse_attempt in range(1, 3):
        predict_meta = {
            "parse_attempt": parse_attempt,
            "clause_id": clause.id,
            "prompt_template_id": ctx.prompt_template_id,
            "predicted_method": "score_clause_risk",
        }
        _emit_event(
            audit,
            weil_audit,
            event_type="TOOL_PREDICT",
            node="risk_score",
            status="ok",
            tool_name="risk_scorer",
            input_payload=payload,
            model=ctx.model,
            metadata=predict_meta,
        )

        result = router.execute_tool("risk_scorer", payload, ctx)
        exec_meta: Dict[str, Any] = {
            "attempts": result.attempts,
            "clause_id": clause.id,
            "method": "score_clause_risk",
            "prompt_template_id": ctx.prompt_template_id,
        }
        token_usage = _extract_token_usage(result.raw)
        if token_usage:
            exec_meta["token_usage"] = token_usage
        _emit_event(
            audit,
            weil_audit,
            event_type="TOOL_EXECUTE",
            node="risk_score",
            status="ok" if result.success else "error",
            tool_name="risk_scorer",
            input_payload=payload,
            output_payload=result.data,
            error=result.error,
            latency_ms=result.latency_ms,
            model=ctx.model,
            metadata=exec_meta,
        )

        if not result.success or not result.data:
            state.fatal_error = True
            state.error_message = result.error or "RISK_SCORE_TOOL_FAILED"
            state.terminate_reason = "TOOL_FAILURE"
            return None

        try:
            risk = score_clause_from_payload(result.data, clause)
            _emit_event(
                audit,
                weil_audit,
                event_type="RISK_SCORED",
                node="risk_score",
                status="ok",
                output_payload={
                    "clause_id": clause.id,
                    "risk_level": risk.risk_level.value,
                    "confidence": risk.confidence,
                },
            )
            return risk
        except Exception as exc:  # noqa: BLE001
            _emit_event(
                audit,
                weil_audit,
                event_type="RISK_PARSE_ERROR",
                node="risk_score",
                status="error",
                error=str(exc),
                output_payload=result.data,
                metadata={"clause_id": clause.id},
            )
            if parse_attempt == 2:
                state.fatal_error = True
                state.error_message = f"RISK_PARSE_ERROR: {exc}"
                state.terminate_reason = "INVALID_TOOL_OUTPUT"
                return None
            payload = {
                "_method": "score_clause_risk",
                "clause_id": clause.id,
                "clause_title": clause.title,
                "clause_text": clause.text,
            }

    return None


def _finalize_result(
    state: AgentState,
    audit: AuditLogger,
    weil_audit: WeilAuditLogger,
    pending_human_review: bool,
) -> AuditResult:
    if state.terminate_reason is None:
        state.terminate_reason = "fatal_error" if state.fatal_error else "complete"

    report = _build_report(state, pending_human_review)
    state.final_report = report["report_text"]

    _emit_event(
        audit,
        weil_audit,
        event_type="TERMINATE",
        node="terminate",
        status="error" if state.fatal_error else ("pending" if pending_human_review else "ok"),
        metadata={
            "reason": state.terminate_reason,
            "fatal_error": state.fatal_error,
            "pending_human_review": pending_human_review,
        },
        error=state.error_message,
    )

    # ── Final on-chain audit record ──────────────────────────────────────
    # Write the complete audit summary to Weilchain as a single final record.
    # This is the canonical transaction that represents the entire audit run.
    # The returned tx_hash is the one surfaced in the report.
    final_tx_hash: Optional[str] = None
    if not pending_human_review and weil_audit.enabled:
        final_audit_payload = {
            "session_id": state.session_id,
            "filename": state.filename,
            "decision": state.human_decision,
            "terminate_reason": state.terminate_reason,
            "summary": report["report_json"].get("summary", {}),
            "event_count": audit.step_index,
            "wallet_address": weil_audit.wallet_address,
        }
        weil_audit.emit("AUDIT_COMPLETE", final_audit_payload)
        # The last tx_result is the AUDIT_COMPLETE write
        if weil_audit.tx_results:
            latest = weil_audit.tx_results[-1]
            final_tx_hash = latest.get("tx_hash")
            # If the AUDIT_COMPLETE write returned IN_PROGRESS, use the hash
            # of the most recent confirmed transaction from earlier events
            if not final_tx_hash:
                for tx in reversed(weil_audit.tx_results):
                    if tx.get("tx_hash"):
                        final_tx_hash = tx["tx_hash"]
                        break

    # Attach the final tx_hash to the report JSON so it flows through to the UI
    report["report_json"]["tx_hash"] = final_tx_hash
    report["report_json"]["weilchain_enabled"] = weil_audit.enabled

    summary_path = Path(audit.runs_dir) / (state.session_id or "unknown") / "audit_summary.json"
    audit.summary(
        summary_path,
        final_status="error" if state.fatal_error else ("pending" if pending_human_review else "ok"),
        extra={
            "terminate_reason": state.terminate_reason,
            "error_message": state.error_message,
            "decision": state.human_decision,
            "weilchain_enabled": weil_audit.enabled,
            "weilchain_tx_count": len(weil_audit.tx_results),
            "weilchain_txns": weil_audit.tx_results,
            "final_tx_hash": final_tx_hash,
        },
    )

    state.step_index = audit.step_index

    return AuditResult(
        session_id=state.session_id or "",
        state=state,
        audit_log=audit.events,
        report_text=report["report_text"],
        report_json=report["report_json"],
        pending_human_review=pending_human_review,
        weil_audit_logger=weil_audit,
        final_tx_hash=final_tx_hash,
    )
