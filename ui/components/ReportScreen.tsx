'use client'
import { useState } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, RadialBarChart, RadialBar
} from 'recharts'
import {
  Download, ExternalLink, Shield, CheckCircle, XCircle,
  Clock, Hash, FileText, ChevronDown, ChevronUp, Link
} from 'lucide-react'
import { useApp, RiskScore, AuditEvent } from '@/lib/store'

const RISK_COLOR: Record<string, string> = {
  HIGH:    '#FF2D78',
  MEDIUM:  '#FFA500',
  LOW:     '#8AFF00',
  UNKNOWN: '#9B5CF6',
}

function RiskBadge({ level }: { level: string }) {
  return (
    <span className={`risk-${level.toLowerCase()} text-xs font-mono px-2 py-0.5 rounded-full`}>
      {level}
    </span>
  )
}

function ClauseRow({ score }: { score: RiskScore }) {
  const [open, setOpen] = useState(false)
  return (
    <div className={`rounded-xl overflow-hidden transition-all border
      ${score.risk_level === 'HIGH'   ? 'border-pink-400/20'   : ''}
      ${score.risk_level === 'MEDIUM' ? 'border-amber-400/15'  : ''}
      ${score.risk_level === 'LOW'    ? 'border-volt/10'       : ''}
      bg-white/2`}
    >
      <button
        className="w-full flex items-center gap-4 p-4 text-left hover:bg-white/3 transition-colors"
        onClick={() => setOpen(!open)}
      >
        <div className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: RISK_COLOR[score.risk_level] }} />
        <span className="flex-1 font-body text-white/80 text-sm">{score.clause_title}</span>
        <RiskBadge level={score.risk_level} />
        <span className="text-white/20 text-xs font-mono">{(parseFloat(String(score.confidence)) * 100).toFixed(0)}%</span>
        {open ? <ChevronUp className="w-4 h-4 text-white/20" /> : <ChevronDown className="w-4 h-4 text-white/20" />}
      </button>
      {open && (
        <div className="px-4 pb-4 border-t border-white/5 pt-3">
          <p className="text-white/40 text-sm mb-3 leading-relaxed">{score.reason}</p>
          {score.flags.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {score.flags.map(f => (
                <span key={f.code} className="font-mono text-xs bg-white/5 border border-white/10 text-white/30 px-2 py-0.5 rounded">
                  {f.code}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function AuditRow({ event, idx }: { event: AuditEvent, idx: number }) {
  const colors: Record<string, string> = {
    INIT_START:      'text-violet-400',
    INGEST_DONE:     'text-cyan-400',
    LLM_INVOKE:      'text-blue-400',
    TOOL_CALL:       'text-amber-400',
    TOOL_RESULT:     'text-amber-300',
    RISK_SCORED:     'text-orange-400',
    HUMAN_GATE:      'text-pink-400',
    HUMAN_DECISION:  'text-pink-300',
    TERMINATE:       'text-volt',
  }
  return (
    <div className="flex items-center gap-3 py-1.5 border-b border-white/3 last:border-0">
      <span className="font-mono text-xs text-white/15 w-6 text-right flex-shrink-0">{idx + 1}</span>
      <span className={`font-mono text-xs flex-shrink-0 w-36 ${colors[event.event] ?? 'text-white/30'}`}>
        {event.event}
      </span>
      <span className="font-mono text-xs text-white/15 flex-1 truncate">
        {new Date(event.timestamp).toISOString()}
      </span>
    </div>
  )
}

export default function ReportScreen() {
  const { result, setActiveScreen } = useApp()
  const [auditOpen, setAuditOpen] = useState(false)

  if (!result) return (
    <div className="min-h-screen flex items-center justify-center">
      <div className="text-white/30 font-mono">No result data found</div>
    </div>
  )

  const high   = result.risk_scores.filter(r => r.risk_level === 'HIGH')
  const medium = result.risk_scores.filter(r => r.risk_level === 'MEDIUM')
  const low    = result.risk_scores.filter(r => r.risk_level === 'LOW')

  const barData = [
    { name: 'HIGH',   count: high.length,   fill: '#FF2D78' },
    { name: 'MEDIUM', count: medium.length,  fill: '#FFA500' },
    { name: 'LOW',    count: low.length,     fill: '#8AFF00' },
  ]

  const radialData = [
    { name: 'Risk Score', value: Math.round((high.length * 3 + medium.length * 1.5) / result.risk_scores.length * 33), fill: '#FF2D78' },
  ]

  const downloadReport = () => {
    const text = `LEXAUDIT — FINAL REPORT
========================
Session: ${result.session_id}
File:    ${result.filename}
Decision: ${result.human_decision?.toUpperCase() ?? 'AUTO'}
Tx Hash: ${result.tx_hash ?? 'pending'}

RISK SUMMARY
HIGH:   ${high.length} clause(s)
MEDIUM: ${medium.length} clause(s)  
LOW:    ${low.length} clause(s)

HIGH RISK CLAUSES
${high.map(r => `• ${r.clause_title}\n  ${r.reason}\n  Flags: ${r.flags.map(f => f.code).join(', ')}`).join('\n\n')}

AUDIT TRAIL
${result.audit_events.length} events logged on Weilchain
`
    const blob = new Blob([text], { type: 'text/plain' })
    const url  = URL.createObjectURL(blob)
    const a    = document.createElement('a')
    a.href = url; a.download = `lexaudit-report-${result.session_id}.txt`
    a.click()
  }

  return (
    <div className="min-h-screen pt-24 pb-16 px-6 max-w-4xl mx-auto">
      {/* Header */}
      <div className="flex items-start justify-between mb-8 gap-4">
        <div>
          <div className="flex items-center gap-3 mb-2">
            {result.human_decision === 'approve'
              ? <CheckCircle className="w-6 h-6 text-volt" />
              : <XCircle    className="w-6 h-6 text-pink-400" />
            }
            <span className={`font-mono text-sm font-bold ${result.human_decision === 'approve' ? 'text-volt' : 'text-pink-400'}`}>
              {result.human_decision === 'approve' ? 'CONTRACT APPROVED' : 'CONTRACT REJECTED'}
            </span>
          </div>
          <h2 className="font-display font-bold text-3xl text-white">Final Report</h2>
          <p className="text-white/30 font-mono text-sm mt-1">{result.filename}</p>
        </div>
        <div className="flex gap-3">
          <button onClick={() => setActiveScreen('upload')}
            className="glass rounded-xl px-4 py-2.5 text-sm font-mono text-white/40 hover:text-white/60 transition-colors">
            New Analysis
          </button>
          <button onClick={downloadReport}
            className="btn-shimmer rounded-xl px-5 py-2.5 text-sm font-bold text-white flex items-center gap-2">
            <Download className="w-4 h-4" />
            Download
          </button>
        </div>
      </div>

      {/* Session metadata */}
      <div className="glass rounded-2xl p-5 mb-6 grid grid-cols-2 md:grid-cols-4 gap-4">
        {[
          { icon: <Hash className="w-4 h-4 text-violet-400" />,  label: 'Session', value: result.session_id },
          { icon: <FileText className="w-4 h-4 text-cyan-400" />, label: 'Clauses', value: `${result.clauses.length} found` },
          { icon: <Clock className="w-4 h-4 text-amber-400" />,  label: 'Audit Events', value: `${result.audit_events.length} logged` },
          { icon: <Link className="w-4 h-4 text-volt" />,         label: 'Tx Hash', value: result.tx_hash ? result.tx_hash.slice(0, 10) + '...' : 'pending' },
        ].map(m => (
          <div key={m.label}>
            <div className="flex items-center gap-2 mb-1">{m.icon}<span className="text-white/30 text-xs font-mono">{m.label}</span></div>
            <div className="font-mono text-sm text-white/70 truncate">{m.value}</div>
          </div>
        ))}
      </div>

      {/* Charts row */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        {/* Risk distribution bar */}
        <div className="md:col-span-2 glass rounded-2xl p-5">
          <h3 className="font-display font-bold text-white mb-4">Risk Distribution</h3>
          <ResponsiveContainer width="100%" height={140}>
            <BarChart data={barData} barSize={40}>
              <XAxis dataKey="name" axisLine={false} tickLine={false}
                tick={{ fill: 'rgba(255,255,255,0.3)', fontSize: 11, fontFamily: 'JetBrains Mono' }} />
              <YAxis hide />
              <Tooltip
                contentStyle={{ background: 'rgba(10,12,24,0.9)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: '8px', fontFamily: 'JetBrains Mono', fontSize: 11 }}
                cursor={{ fill: 'rgba(255,255,255,0.03)' }}
              />
              <Bar dataKey="count" radius={[6,6,0,0]}>
                {barData.map((d, i) => <Cell key={i} fill={d.fill} fillOpacity={0.8} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Risk summary cards */}
        <div className="flex flex-col gap-3">
          {[
            { label: 'HIGH',   count: high.length,   color: 'risk-high',   glow: 'border-glow-pink' },
            { label: 'MEDIUM', count: medium.length,  color: 'risk-medium', glow: '' },
            { label: 'LOW',    count: low.length,     color: 'risk-low',    glow: 'border-glow-volt' },
          ].map(r => (
            <div key={r.label} className={`glass rounded-xl p-4 flex items-center justify-between ${r.count > 0 && r.label === 'HIGH' ? r.glow : ''}`}>
              <span className={`${r.color} text-xs font-mono px-2 py-0.5 rounded-full`}>{r.label}</span>
              <span className="font-display font-bold text-2xl text-white">{r.count}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Clause risk list */}
      <div className="glass rounded-2xl p-5 mb-6">
        <h3 className="font-display font-bold text-white mb-4">Clause Analysis</h3>
        <div className="space-y-2">
          {result.risk_scores.map(score => <ClauseRow key={score.clause_id} score={score} />)}
        </div>
      </div>

      {/* On-chain audit trail */}
      <div className="glass rounded-2xl overflow-hidden mb-6">
        <button
          className="w-full flex items-center justify-between p-5 hover:bg-white/2 transition-colors"
          onClick={() => setAuditOpen(!auditOpen)}
        >
          <div className="flex items-center gap-3">
            <div className="w-2 h-2 rounded-full bg-volt animate-pulse" />
            <h3 className="font-display font-bold text-white">On-Chain Audit Trail</h3>
            <span className="font-mono text-xs text-volt/60 glass rounded-full px-2 py-0.5">
              {result.audit_events.length} events
            </span>
          </div>
          {auditOpen ? <ChevronUp className="w-5 h-5 text-white/30" /> : <ChevronDown className="w-5 h-5 text-white/30" />}
        </button>

        {auditOpen && (
          <div className="border-t border-white/5 p-5">
            {/* Chain info */}
            <div className="flex items-center gap-4 mb-4 glass rounded-xl p-3">
              <Shield className="w-4 h-4 text-volt" />
              <div className="flex-1">
                <div className="font-mono text-xs text-white/30">Weilchain Transaction</div>
                <div className="font-mono text-xs text-volt/80 mt-0.5">{result.tx_hash}</div>
              </div>
              <button className="text-white/20 hover:text-white/50 transition-colors">
                <ExternalLink className="w-4 h-4" />
              </button>
            </div>

            {/* Events */}
            <div className="max-h-64 overflow-y-auto pr-1">
              {result.audit_events.map((e, i) => <AuditRow key={i} event={e} idx={i} />)}
            </div>
          </div>
        )}
      </div>

      {/* Note about on-chain */}
      <div className="glass rounded-xl p-4 border border-volt/10 flex items-start gap-3">
        <div className="w-1.5 h-1.5 rounded-full bg-volt mt-1.5 flex-shrink-0" />
        <p className="text-white/30 text-xs font-mono leading-relaxed">
          Audit trail is currently stored locally. After Weilchain deployment, all{' '}
          {result.audit_events.length} events will be cryptographically signed on-chain
          via <span className="text-volt/60">ctx.emit()</span> and verifiable by any party
          using the session ID above.
        </p>
      </div>
    </div>
  )
}
