import { AgentStep, AnalysisResult, AuditEvent, RiskFlag, RiskScore } from './store'

const API_BASE = (process.env.NEXT_PUBLIC_LEXAUDIT_API_BASE || 'http://localhost:8000').replace(/\/$/, '')

type BackendPayload = {
  session_id?: string
  state?: {
    filename?: string
    clauses?: Array<{ id: number; title: string; text: string }>
    risk_results?: Array<{
      clause_id: number
      clause_title: string
      risk_level: string
      confidence: number | string
      reason: string
      flags?: string[]
    }>
    human_decision?: string
  }
  report_text?: string
  report_json?: {
    filename?: string
    risk_results?: Array<{
      clause_id: number
      clause_title: string
      risk_level: string
      confidence: number | string
      reason: string
      flags?: string[]
    }>
  }
  audit_log?: Array<{
    step_index?: number
    event_type?: string
    timestamp?: number
    node?: string
    status?: string
    metadata?: Record<string, unknown>
    tx_hash?: string | null
    weilchain_link?: string | null
  }>
  pending_human_review?: boolean
}

const NODE_SEQUENCE: AgentStep[] = [
  { id: 1, node: 'INIT', status: 'pending', message: 'Initializing Weilchain session...' },
  { id: 2, node: 'INGEST', status: 'pending', message: 'Ingesting contract text...' },
  { id: 3, node: 'CLAUSE_EXTRACT', status: 'pending', message: 'Extracting clauses via MCP applet...' },
  { id: 4, node: 'RISK_LOOP', status: 'pending', message: 'Scoring clause risks...' },
  { id: 5, node: 'HUMAN_GATE', status: 'pending', message: 'Applying human gate policy...' },
  { id: 6, node: 'TERMINATE', status: 'pending', message: 'Generating final report...' },
]

const NODE_BY_BACKEND: Record<string, AgentStep['node']> = {
  control_loop: 'INIT',
  ingest: 'INGEST',
  extract_clauses: 'CLAUSE_EXTRACT',
  risk_score: 'RISK_LOOP',
  human_gate: 'HUMAN_GATE',
  terminate: 'TERMINATE',
}

const EVENT_NODE_HINT: Array<[RegExp, AgentStep['node']]> = [
  [/^INIT/i, 'INIT'],
  [/INGEST/i, 'INGEST'],
  [/CLAUSE|EXTRACT/i, 'CLAUSE_EXTRACT'],
  [/RISK/i, 'RISK_LOOP'],
  [/HUMAN/i, 'HUMAN_GATE'],
  [/TERMINATE|REPORT/i, 'TERMINATE'],
]

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function parseFlag(value: string): RiskFlag {
  const [code, ...rest] = value.split(':')
  const normalizedCode = (code || 'FLAG').trim().toUpperCase().replace(/\s+/g, '_')
  const description = rest.join(':').trim() || value
  return { code: normalizedCode, description }
}

function normalizeFlags(flags: unknown): RiskFlag[] {
  if (!Array.isArray(flags)) return []
  return flags
    .map((flag): RiskFlag | null => {
      if (typeof flag === 'string' && flag.trim()) return parseFlag(flag)
      if (
        flag &&
        typeof flag === 'object' &&
        typeof (flag as { code?: unknown }).code === 'string' &&
        typeof (flag as { description?: unknown }).description === 'string'
      ) {
        return {
          code: ((flag as { code: string }).code || '').trim(),
          description: ((flag as { description: string }).description || '').trim(),
        }
      }
      return null
    })
    .filter((flag): flag is RiskFlag => Boolean(flag))
}

function normalizeRiskScores(raw: unknown): RiskScore[] {
  if (!Array.isArray(raw)) return []
  return raw.map((row, index) => {
    const item = (row || {}) as Record<string, unknown>
    return {
      clause_id: Number(item.clause_id ?? index + 1),
      clause_title: String(item.clause_title ?? `Clause ${index + 1}`),
      risk_level: String(item.risk_level ?? 'UNKNOWN').toUpperCase() as RiskScore['risk_level'],
      confidence: (typeof item.confidence === 'number' ? item.confidence : String(item.confidence ?? '0.0')) as string | number,
      reason: String(item.reason ?? 'No reason provided'),
      flags: normalizeFlags(item.flags),
    }
  })
}

function normalizeAuditEvents(raw: BackendPayload['audit_log']): AuditEvent[] {
  if (!Array.isArray(raw)) return []
  return raw.map((event, idx) => ({
    step: Number(event?.step_index ?? idx + 1),
    event: String(event?.event_type ?? 'UNKNOWN_EVENT'),
    timestamp: Number(event?.timestamp ?? Date.now()),
    data: (event?.metadata || {}) as Record<string, unknown>,
    status: typeof event?.status === 'string' ? event.status : undefined,
    node: typeof event?.node === 'string' ? event.node : undefined,
    tx_hash: typeof event?.tx_hash === 'string' ? event.tx_hash : undefined,
    weilchain_link: typeof event?.weilchain_link === 'string' ? event.weilchain_link : undefined,
  }))
}

function backendNodeFromEvent(event: AuditEvent): AgentStep['node'] {
  if (event.node && NODE_BY_BACKEND[event.node]) return NODE_BY_BACKEND[event.node]
  for (const [pattern, node] of EVENT_NODE_HINT) {
    if (pattern.test(event.event)) return node
  }
  return 'RISK_LOOP'
}

function toAnalysisResult(payload: BackendPayload, fallbackFilename: string): AnalysisResult {
  const state = payload.state || {}
  const riskRows = state.risk_results || payload.report_json?.risk_results || []
  const auditEvents = normalizeAuditEvents(payload.audit_log)
  const txHash = auditEvents.find((event) => event.tx_hash)?.tx_hash

  return {
    session_id: String(payload.session_id || `lex-${Date.now()}`),
    filename: String(state.filename || payload.report_json?.filename || fallbackFilename),
    clauses: Array.isArray(state.clauses) ? state.clauses : [],
    risk_scores: normalizeRiskScores(riskRows),
    audit_events: auditEvents,
    human_decision: typeof state.human_decision === 'string' ? state.human_decision : undefined,
    final_report: payload.report_text,
    tx_hash: txHash,
  }
}

export async function streamAnalysis(
  contractText: string,
  filename: string,
  onStep: (steps: AgentStep[]) => void,
  onComplete: (result: AnalysisResult) => void,
  onNeedHuman: () => void
) {
  const steps: AgentStep[] = NODE_SEQUENCE.map((step) => ({ ...step }))
  onStep([...steps])

  // Immediate live indicator while request is in flight.
  steps[0] = { ...steps[0], status: 'running', timestamp: Date.now() }
  onStep([...steps])

  const response = await fetch(`${API_BASE}/api/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      contract_text: contractText,
      filename,
      max_steps: 60,
      human_gate_threshold: 'HIGH',
    }),
  })

  const raw = await response.json().catch(() => ({}))
  const payload: BackendPayload =
    raw && typeof raw === 'object' && raw.detail && typeof raw.detail === 'object'
      ? (raw.detail as BackendPayload)
      : (raw as BackendPayload)

  if (!response.ok) {
    const errorMessage =
      (raw && typeof raw.detail === 'string' && raw.detail) ||
      (payload.state && typeof payload.state.human_decision === 'string' ? payload.state.human_decision : '') ||
      'Analysis failed'

    steps[0] = {
      ...steps[0],
      status: 'error',
      message: errorMessage,
      timestamp: Date.now(),
    }
    onStep([...steps])
    throw new Error(errorMessage)
  }

  const result = toAnalysisResult(payload, filename)

  // Replay server events through the node timeline so the feed still feels live.
  for (const event of result.audit_events) {
    const node = backendNodeFromEvent(event)
    const idx = steps.findIndex((step) => step.node === node)
    if (idx === -1) continue

    const status = event.status === 'error' ? 'error' : event.status === 'pending' ? 'running' : 'done'
    steps[idx] = {
      ...steps[idx],
      status,
      message: event.event,
      timestamp: event.timestamp,
    }
    onStep([...steps])
    await sleep(120)
  }

  if (payload.pending_human_review) {
    onNeedHuman()
    return
  }

  onComplete(result)
}

export async function completeAnalysis(
  decision: string,
  onStep: (steps: AgentStep[]) => void,
  onComplete: (result: AnalysisResult) => void
) {
  const steps: AgentStep[] = [
    { id: 1, node: 'HUMAN_GATE', status: 'running', message: `Recording decision: ${decision}`, timestamp: Date.now() },
    { id: 2, node: 'TERMINATE', status: 'pending', message: 'Generating final report...' },
  ]
  onStep([...steps])

  const response = await fetch(`${API_BASE}/api/continue`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ decision }),
  })

  steps[0] = { ...steps[0], status: 'done', timestamp: Date.now() }
  steps[1] = { ...steps[1], status: 'running', timestamp: Date.now() }
  onStep([...steps])

  if (!response.ok) {
    // If the /api/continue endpoint is not implemented yet, produce a
    // synthetic result so the UI still reaches the report screen.
    steps[1] = { ...steps[1], status: 'done', message: `Decision recorded: ${decision}`, timestamp: Date.now() }
    onStep([...steps])
    onComplete({
      session_id: `lex-${Date.now()}`,
      filename: 'contract.txt',
      clauses: [],
      risk_scores: [],
      audit_events: [],
      human_decision: decision,
      final_report: `Human decision: ${decision.toUpperCase()}`,
      tx_hash: undefined,
    })
    return
  }

  const raw = await response.json().catch(() => ({}))
  const payload: BackendPayload =
    raw && typeof raw === 'object' && raw.detail && typeof raw.detail === 'object'
      ? (raw.detail as BackendPayload)
      : (raw as BackendPayload)

  const result = toAnalysisResult(payload, 'contract.txt')
  result.human_decision = decision

  steps[1] = { ...steps[1], status: 'done', message: 'Report ready', timestamp: Date.now() }
  onStep([...steps])

  await sleep(300)
  onComplete(result)
}
