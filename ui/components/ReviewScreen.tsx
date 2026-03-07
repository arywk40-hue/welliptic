'use client'
import { useState } from 'react'
import { AlertTriangle, CheckCircle, XCircle, Eye, ChevronDown, ChevronUp } from 'lucide-react'
import { useApp, RiskScore } from '@/lib/store'
import { completeAnalysis } from '@/lib/api'

interface ReviewClause {
  clause_id: number
  clause_title: string
  risk_level: string
  confidence: string | number
  reason: string
  flags: { code: string; description: string }[]
  text?: string
}

function toReviewClause(score: RiskScore, clauses: { id: number; text: string }[]): ReviewClause {
  const clause = clauses.find(c => c.id === score.clause_id)
  return {
    clause_id: score.clause_id,
    clause_title: score.clause_title,
    risk_level: score.risk_level,
    confidence: score.confidence,
    reason: score.reason,
    flags: score.flags,
    text: clause?.text,
  }
}

function ClauseCard({ clause }: { clause: ReviewClause }) {
  const [expanded, setExpanded] = useState(false)
  return (
    <div className="glass rounded-xl overflow-hidden border border-pink-400/20">
      <div className="p-5">
        <div className="flex items-start justify-between gap-4 mb-3">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg risk-high flex items-center justify-center flex-shrink-0">
              <AlertTriangle className="w-4 h-4" />
            </div>
            <div>
              <div className="font-display font-bold text-white">{clause.clause_title}</div>
              <div className="flex items-center gap-2 mt-0.5">
                <span className={`risk-${clause.risk_level.toLowerCase()} text-xs font-mono px-2 py-0.5 rounded-full`}>{clause.risk_level} RISK</span>
                <span className="text-white/30 text-xs font-mono">confidence {(parseFloat(String(clause.confidence)) * 100).toFixed(0)}%</span>
              </div>
            </div>
          </div>
          <button onClick={() => setExpanded(!expanded)} className="text-white/30 hover:text-white/60 transition-colors">
            {expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </button>
        </div>
        <p className="text-white/50 text-sm leading-relaxed">{clause.reason}</p>

        {/* Flags */}
        <div className="flex flex-wrap gap-2 mt-3">
          {clause.flags.map(f => (
            <span key={f.code} className="font-mono text-xs bg-pink-400/10 border border-pink-400/20 text-pink-300/70 px-2 py-0.5 rounded">
              {f.code}
            </span>
          ))}
        </div>

        {/* Expanded clause text */}
        {expanded && (
          <div className="mt-4 p-3 bg-white/3 rounded-lg border border-white/5">
            <div className="flex items-center gap-2 mb-2">
              <Eye className="w-3 h-3 text-white/20" />
              <span className="font-mono text-xs text-white/20">Original Clause Text</span>
            </div>
            <p className="text-white/40 text-sm font-mono leading-relaxed italic">"{clause.text}"</p>
          </div>
        )}
      </div>
    </div>
  )
}

export default function ReviewScreen() {
  const { result, setActiveScreen, setHumanDecision, setSteps, setResult } = useApp()
  const [deciding, setDeciding] = useState(false)

  // Pull HIGH risk clauses from actual analysis result; fall back to all risk scores
  const highRiskClauses: ReviewClause[] = result
    ? result.risk_scores
        .filter(r => r.risk_level === 'HIGH')
        .map(r => toReviewClause(r, result.clauses))
    : []

  // If no HIGH-risk found, show MEDIUM ones (so review screen is never empty)
  const reviewClauses: ReviewClause[] = highRiskClauses.length > 0
    ? highRiskClauses
    : (result?.risk_scores
        .filter(r => r.risk_level === 'MEDIUM')
        .map(r => toReviewClause(r, result.clauses)) ?? [])

  const decide = async (decision: 'approve' | 'reject') => {
    setDeciding(true)
    setHumanDecision(decision)
    await completeAnalysis(
      decision,
      setSteps,
      (result) => {
        setResult(result)
        setActiveScreen('report')
      }
    )
  }

  return (
    <div className="min-h-screen pt-24 pb-16 px-6 max-w-3xl mx-auto">
      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center gap-3 mb-4">
          <div className="relative">
            <div className="w-10 h-10 rounded-xl bg-pink-400/20 border border-pink-400/30 flex items-center justify-center">
              <AlertTriangle className="w-5 h-5 text-pink-400" />
            </div>
            {/* Pulse rings */}
            <div className="absolute inset-0 rounded-xl border border-pink-400/30 animate-ping" />
          </div>
          <div>
            <div className="font-mono text-xs text-pink-400 mb-0.5">HUMAN-IN-THE-LOOP GATE</div>
            <h2 className="font-display font-bold text-2xl text-white">Review Required</h2>
          </div>
        </div>
        <div className="glass rounded-xl p-4 border border-amber-400/20">
          <p className="text-white/60 text-sm leading-relaxed">
            The AI agent identified <span className="text-pink-400 font-bold">{reviewClauses.length} flagged clause{reviewClauses.length !== 1 ? 's' : ''}</span> that
            require human review before proceeding. Your decision will be cryptographically signed
            and recorded on Weilchain as an immutable audit event.
          </p>
        </div>
      </div>

      {/* Risk cards */}
      <div className="space-y-4 mb-8">
        {reviewClauses.map(c => <ClauseCard key={c.clause_id} clause={c} />)}
      </div>

      {/* Decision buttons */}
      {!deciding ? (
        <div className="glass rounded-2xl p-6 border border-white/5">
          <p className="font-mono text-xs text-white/30 text-center mb-5">
            Your decision will be logged on-chain with timestamp and session ID
          </p>
          <div className="grid grid-cols-2 gap-4">
            <button
              onClick={() => decide('reject')}
              className="group flex flex-col items-center gap-2 p-5 rounded-xl border border-pink-400/30 bg-pink-400/5 hover:bg-pink-400/10 hover:border-pink-400/60 transition-all duration-200"
            >
              <XCircle className="w-8 h-8 text-pink-400 group-hover:scale-110 transition-transform" />
              <span className="font-display font-bold text-white">Reject Contract</span>
              <span className="text-pink-400/60 text-xs font-mono">Flag for renegotiation</span>
            </button>
            <button
              onClick={() => decide('approve')}
              className="group flex flex-col items-center gap-2 p-5 rounded-xl border border-volt/30 bg-volt/5 hover:bg-volt/10 hover:border-volt/60 transition-all duration-200"
            >
              <CheckCircle className="w-8 h-8 text-volt group-hover:scale-110 transition-transform" />
              <span className="font-display font-bold text-white">Approve Contract</span>
              <span className="text-volt/60 text-xs font-mono">Accept with risk flags</span>
            </button>
          </div>
        </div>
      ) : (
        <div className="glass rounded-2xl p-8 text-center border border-cyan-400/20">
          <div className="w-12 h-12 rounded-full border-2 border-cyan-400/40 border-t-cyan-400 animate-spin mx-auto mb-4" />
          <p className="text-cyan-400 font-mono text-sm">Committing decision to Weilchain...</p>
          <p className="text-white/20 font-mono text-xs mt-1">Generating final report</p>
        </div>
      )}
    </div>
  )
}
