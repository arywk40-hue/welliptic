'use client'
import { useEffect, useState } from 'react'
import { Shield, Zap } from 'lucide-react'

const LLM_LABELS: Record<string, string> = {
  groq:      'Groq · Llama 3.3 70B',
  gemini:    'Gemini 2.0 Flash',
  openai:    'GPT-4o',
  anthropic: 'Claude Opus 4.1',
  none:      'No LLM',
}

export default function Navbar() {
  const [llmLabel, setLlmLabel]     = useState('...')
  const [weilOk,   setWeilOk]       = useState(false)
  const [mcp,      setMcp]          = useState('')

  useEffect(() => {
    fetch('/api/health')
      .then(r => r.json())
      .then(d => {
        setLlmLabel(LLM_LABELS[d.llm_provider] ?? d.llm_provider)
        setWeilOk(d.weil_middleware ?? d.weilchain ?? false)
        setMcp(d.mcp_mode ?? '')
      })
      .catch(() => setLlmLabel('offline'))
  }, [])

  return (
    <nav className="fixed top-0 left-0 right-0 z-50 glass border-b border-white/5">
      <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
        {/* Logo */}
        <div className="flex items-center gap-3">
          <div className="relative">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-violet-500 to-cyan-400 flex items-center justify-center">
              <Shield className="w-4 h-4 text-white" />
            </div>
            <div className="absolute -top-1 -right-1 w-3 h-3 rounded-full bg-volt animate-pulse" />
          </div>
          <span className="font-display font-bold text-lg tracking-tight">
            Lex<span className="grad-cyan">Audit</span>
          </span>
        </div>

        {/* Weilchain status pill */}
        <div className="flex items-center gap-2 glass rounded-full px-4 py-1.5 text-xs font-mono">
          <div className={`w-1.5 h-1.5 rounded-full animate-pulse ${weilOk ? 'bg-volt' : 'bg-orange-400'}`} />
          <span className="text-white/50">Weilchain</span>
          <span className={weilOk ? 'text-volt' : 'text-orange-400'}>
            {weilOk ? (mcp === 'real' ? 'MAINNET' : 'TESTNET') : 'LOCAL'}
          </span>
        </div>

        {/* LLM pill — live from /api/health */}
        <div className="flex items-center gap-3">
          <div className="glass rounded-lg px-3 py-1.5 text-xs font-mono text-white/40 flex items-center gap-2">
            <Zap className="w-3 h-3 text-cyan-400" />
            {llmLabel}
          </div>
        </div>
      </div>
    </nav>
  )
}
