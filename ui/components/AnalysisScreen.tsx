'use client'
import { useEffect, useRef, useState } from 'react'
import { CheckCircle, Circle, Loader, XCircle, Terminal, Cpu } from 'lucide-react'
import { useApp, AgentStep } from '@/lib/store'
import { streamAnalysis } from '@/lib/api'

const NODE_COLORS: Record<string, string> = {
  INIT:           'text-violet-400',
  INGEST:         'text-cyan-400',
  CLAUSE_EXTRACT: 'text-blue-400',
  RISK_LOOP:      'text-amber-400',
  HUMAN_GATE:     'text-pink-400',
  TERMINATE:      'text-volt',
}

const NODE_LABELS: Record<string, string> = {
  INIT:           'Initialize',
  INGEST:         'Ingest',
  CLAUSE_EXTRACT: 'Extract',
  RISK_LOOP:      'Score Risk',
  HUMAN_GATE:     'Human Gate',
  TERMINATE:      'Terminate',
}

function StepIcon({ status }: { status: AgentStep['status'] }) {
  if (status === 'done')    return <CheckCircle className="w-5 h-5 text-volt flex-shrink-0" />
  if (status === 'running') return <Loader className="w-5 h-5 text-cyan-400 flex-shrink-0 animate-spin" />
  if (status === 'error')   return <XCircle className="w-5 h-5 text-pink-400 flex-shrink-0" />
  return <Circle className="w-5 h-5 text-white/15 flex-shrink-0" />
}

export default function AnalysisScreen() {
  const { contractText, filename, steps, setSteps, setResult, setActiveScreen } = useApp()
  const started = useRef(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (started.current) return
    started.current = true

    streamAnalysis(
      contractText,
      filename,
      setSteps,
      (result) => {
        setResult(result)
        setActiveScreen('report')
      },
      () => setActiveScreen('review')
    ).catch((err: unknown) => {
      const message = err instanceof Error ? err.message : 'Analysis failed'
      setError(message)
    })
  }, [])

  const doneCount = steps.filter(s => s.status === 'done').length
  const progress  = steps.length > 0 ? (doneCount / steps.length) * 100 : 0

  return (
    <div className="min-h-screen pt-24 pb-16 px-6 max-w-4xl mx-auto">
      {/* Header */}
      <div className="mb-10">
        <div className="flex items-center gap-3 mb-3">
          <div className="relative">
            <Cpu className="w-6 h-6 text-cyan-400" />
            <div className="absolute inset-0 rounded-full border border-cyan-400/30 animate-ping" />
          </div>
          <span className="font-mono text-sm text-cyan-400">AGENT RUNNING</span>
        </div>
        <h2 className="font-display font-bold text-3xl text-white mb-2">Live Analysis</h2>
        <p className="text-white/30 font-mono text-sm">{filename || 'contract.txt'}</p>
      </div>

      {/* Progress bar */}
      <div className="glass rounded-2xl p-6 mb-6">
        <div className="flex justify-between items-center mb-3">
          <span className="font-mono text-xs text-white/40">Overall Progress</span>
          <span className="font-mono text-xs text-cyan-400">{Math.round(progress)}%</span>
        </div>
        <div className="h-1.5 bg-white/5 rounded-full overflow-hidden">
          <div className="progress-bar h-full rounded-full" style={{ width: `${progress}%` }} />
        </div>
        <div className="flex justify-between mt-3">
          <span className="font-mono text-xs text-white/20">{doneCount} of {steps.length} nodes complete</span>
          <span className="font-mono text-xs text-white/20">
            {steps.find(s => s.status === 'running')?.node ?? 'Waiting...'}
          </span>
        </div>
      </div>

      {/* Steps feed */}
      <div className="glass rounded-2xl overflow-hidden mb-6">
        <div className="border-b border-white/5 px-6 py-3 flex items-center gap-2">
          <Terminal className="w-4 h-4 text-white/30" />
          <span className="font-mono text-xs text-white/30">Agent Node Feed</span>
        </div>
        <div className="p-4 space-y-2">
          {steps.length === 0 ? (
            <div className="text-white/20 font-mono text-sm text-center py-8">Initializing agent...</div>
          ) : steps.map(step => (
            <div key={step.id}
              className={`flex items-start gap-4 p-3 rounded-xl transition-all duration-300
                ${step.status === 'running' ? 'bg-cyan-400/5 border border-cyan-400/15' : ''}
                ${step.status === 'done'    ? 'opacity-70' : ''}
                ${step.status === 'pending' ? 'opacity-30' : ''}`}
            >
              <StepIcon status={step.status} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-0.5">
                  <span className={`font-mono text-xs font-bold ${NODE_COLORS[step.node] ?? 'text-white/40'}`}>
                    {NODE_LABELS[step.node] ?? step.node}
                  </span>
                  {step.status === 'running' && (
                    <span className="text-xs text-cyan-400/60 font-mono animate-pulse">● ACTIVE</span>
                  )}
                </div>
                <p className="text-white/50 text-sm font-mono truncate">{step.message}</p>
                {step.timestamp && (
                  <p className="text-white/15 text-xs font-mono mt-0.5">
                    {new Date(step.timestamp).toLocaleTimeString()}
                  </p>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Weilchain audit log preview */}
      <div className="glass rounded-2xl p-5">
        <div className="flex items-center gap-2 mb-4">
          <div className="w-2 h-2 rounded-full bg-volt animate-pulse" />
          <span className="font-mono text-xs text-volt">AUDIT LOG — WEILCHAIN TESTNET</span>
        </div>
        <div className="space-y-1">
          {steps.filter(s => s.status === 'done').slice(-4).map((s, i) => (
            <div key={i} className="font-mono text-xs text-white/20 flex gap-3">
              <span className="text-white/10">{i + 1}</span>
              <span className={NODE_COLORS[s.node] ?? 'text-white/20'}>{s.node}_DONE</span>
              <span className="text-white/10">{s.timestamp ? new Date(s.timestamp).toISOString() : '--'}</span>
            </div>
          ))}
          {steps.filter(s => s.status === 'done').length === 0 && (
            <div className="font-mono text-xs text-white/15">Waiting for first event...</div>
          )}
        </div>
      </div>

      {error && (
        <div className="mt-4 glass rounded-xl border border-pink-400/30 p-4">
          <div className="font-mono text-xs text-pink-300">{error}</div>
        </div>
      )}
    </div>
  )
}
