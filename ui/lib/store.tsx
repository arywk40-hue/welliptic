'use client'
import { createContext, useContext, useState, ReactNode } from 'react'

export type RiskLevel = 'HIGH' | 'MEDIUM' | 'LOW' | 'UNKNOWN'

export interface Clause {
  id: number
  title: string
  text: string
}

export interface RiskFlag {
  code: string
  description: string
}

export interface RiskScore {
  clause_id: number
  clause_title: string
  risk_level: RiskLevel
  confidence: string | number
  reason: string
  flags: RiskFlag[]
}

export interface AuditEvent {
  step: number
  event: string
  timestamp: number
  data: Record<string, unknown>
  status?: string
  node?: string
  tx_hash?: string
  weilchain_link?: string
}

export interface AnalysisResult {
  session_id: string
  filename: string
  clauses: Clause[]
  risk_scores: RiskScore[]
  audit_events: AuditEvent[]
  human_decision?: string
  final_report?: string
  tx_hash?: string
}

export interface AgentStep {
  id: number
  node: string
  status: 'pending' | 'running' | 'done' | 'error'
  message: string
  timestamp?: number
}

interface AppState {
  filename: string
  contractText: string
  steps: AgentStep[]
  result: AnalysisResult | null
  humanDecision: string | null
  activeScreen: 'upload' | 'analysis' | 'review' | 'report'
  setFilename: (n: string) => void
  setContractText: (t: string) => void
  setSteps: (s: AgentStep[]) => void
  setResult: (r: AnalysisResult) => void
  setHumanDecision: (d: string) => void
  setActiveScreen: (s: AppState['activeScreen']) => void
}

const AppCtx = createContext<AppState | null>(null)

export function AppProvider({ children }: { children: ReactNode }) {
  const [filename, setFilename]           = useState('')
  const [contractText, setContractText]   = useState('')
  const [steps, setSteps]                 = useState<AgentStep[]>([])
  const [result, setResult]               = useState<AnalysisResult | null>(null)
  const [humanDecision, setHumanDecision] = useState<string | null>(null)
  const [activeScreen, setActiveScreen]   = useState<AppState['activeScreen']>('upload')

  return (
    <AppCtx.Provider value={{
      filename, contractText, steps, result, humanDecision, activeScreen,
      setFilename, setContractText, setSteps, setResult, setHumanDecision, setActiveScreen
    }}>
      {children}
    </AppCtx.Provider>
  )
}

export function useApp() {
  const ctx = useContext(AppCtx)
  if (!ctx) throw new Error('useApp must be inside AppProvider')
  return ctx
}
