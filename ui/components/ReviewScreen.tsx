'use client'
import { useState } from 'react'
import { AlertTriangle, CheckCircle, XCircle, Eye, ChevronDown, ChevronUp } from 'lucide-react'
import { useApp } from '@/lib/store'
import { completeAnalysis } from '@/lib/api'

const MOCK_HIGH_RISK = [
  {
    clause_id: 2,
    clause_title: 'Intellectual Property',
    risk_level: 'HIGH' as const,
    confidence: '0.94',
    reason: 'Client receives no ownership of work product — all IP retained by Consultant',
    flags: [
      { code: 'IP_OWNERSHIP', description: 'All IP retained by consultant, not client' },
      { code: 'REVOCABLE_LICENSE', description: 'License can be revoked at any time without notice' },
    ],
    text: 'All work product created by Consultant remains the exclusive property of Consultant. Client receives a limited, revocable, non-transferable license only.'
  },
  {
    clause_id: 3,
    clause_title: 'Non-Compete',
    risk_level: 'HIGH' as const,
    confidence: '0.97',
    reason: '10-year worldwide non-compete is unreasonable and unenforceable in most jurisdictions',
    flags: [
      { code: 'UNREASONABLE_SCOPE', description: 'Worldwide + 10 years far exceeds legal standards' },
      { code: 'UNENFORCEABLE', description: 'Likely void in most US states and EU jurisdictions' },
    ],
    text: 'Consultant shall not work for any company in any industry for 10 years after termination of this agreement, worldwide and without geographic limitation.'
  },
  {
    clause_id: 4,
    clause_title: 'Liability',
    risk_level: 'HIGH' as const,
    confidence: '0.91',
    reason: 'Unlimited irrevocable liability creates catastrophic financial exposure for client',
    flags: [
      { code: 'UNLIMITED_LIABILITY', description: 'No cap on damages — unlimited exposure' },
      { code: 'IRREVOCABLE', description: 'Cannot be limited or modified after signing' },
    ],
    text: 'Client assumes full and unlimited liability for any damages. Consultant liability is unlimited and irrevocably survives contract termination.'
  },
]

function ClauseCard({ clause }: { clause: typeof MOCK_HIGH_RISK[0] }) {
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
                <span className="risk-high text-xs font-mono px-2 py-0.5 rounded-full">HIGH RISK</span>
                <span className="text-white/30 text-xs font-mono">confidence {(parseFloat(clause.confidence) * 100).toFixed(0)}%</span>
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
  const { setActiveScreen, setHumanDecision, setSteps, setResult } = useApp()
  const [deciding, setDeciding] = useState(false)

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
            The AI agent identified <span className="text-pink-400 font-bold">{MOCK_HIGH_RISK.length} HIGH risk clauses</span> that
            require human review before proceeding. Your decision will be cryptographically signed
            and recorded on Weilchain as an immutable audit event.
          </p>
        </div>
      </div>

      {/* Risk cards */}
      <div className="space-y-4 mb-8">
        {MOCK_HIGH_RISK.map(c => <ClauseCard key={c.clause_id} clause={c} />)}
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
