'use client'
import { useCallback, useState } from 'react'
import { Upload, FileText, Zap, Shield, ChevronRight } from 'lucide-react'
import { useApp } from '@/lib/store'

export default function UploadScreen() {
  const { setFilename, setContractText, setActiveScreen } = useApp()
  const [dragging, setDragging] = useState(false)
  const [loaded, setLoaded]     = useState(false)
  const [fname, setFname]       = useState('')

  const processFile = useCallback((file: File) => {
    setFname(file.name)
    setFilename(file.name)
    const reader = new FileReader()
    reader.onload = e => {
      setContractText(e.target?.result as string)
      setLoaded(true)
    }
    reader.readAsText(file)
  }, [setFilename, setContractText])

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragging(false)
    const file = e.dataTransfer.files[0]
    if (file) processFile(file)
  }, [processFile])

  const onFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) processFile(file)
  }

  return (
    <div className="min-h-screen pt-24 pb-16 px-6 flex flex-col items-center justify-center">
      {/* Hero */}
      <div className="text-center mb-12 max-w-2xl">
        <div className="inline-flex items-center gap-2 glass rounded-full px-4 py-1.5 text-xs font-mono text-cyan-400 mb-6">
          <div className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-pulse" />
          Powered by Weilchain MCP Applets
        </div>
        <h1 className="font-display font-bold text-5xl md:text-6xl leading-tight mb-4">
          <span className="text-white">AI Legal Review</span>
          <br />
          <span className="grad-cyan">Verifiably On-Chain</span>
        </h1>
        <p className="text-white/40 text-lg font-body leading-relaxed">
          Every clause scored. Every decision signed. Every audit trail immutable on Weilchain.
        </p>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-3 gap-4 mb-10 w-full max-w-lg">
        {[
          { label: 'Audit Events', value: '29+', color: 'cyan' },
          { label: 'On-Chain Steps', value: '100%', color: 'volt' },
          { label: 'MCP Applets', value: '2', color: 'violet' },
        ].map(s => (
          <div key={s.label} className="glass rounded-xl p-4 text-center">
            <div className={`font-display font-bold text-2xl grad-${s.color}`}>{s.value}</div>
            <div className="text-white/30 text-xs font-mono mt-1">{s.label}</div>
          </div>
        ))}
      </div>

      {/* Drop zone */}
      <div className="w-full max-w-2xl">
        <div
          onDragOver={e => { e.preventDefault(); setDragging(true) }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={`relative scanline rounded-2xl border-2 border-dashed transition-all duration-300 p-12 text-center cursor-pointer
            ${dragging ? 'drop-active border-cyan-400' : 'border-white/10 hover:border-white/20'}
            ${loaded ? 'border-volt/50 bg-volt/5' : 'glass'}`}
          onClick={() => document.getElementById('file-input')?.click()}
        >
          <input id="file-input" type="file" accept=".txt,.pdf,.doc,.docx"
            className="hidden" onChange={onFileInput} />

          {loaded ? (
            <div className="flex flex-col items-center gap-3">
              <div className="w-16 h-16 rounded-2xl bg-volt/20 flex items-center justify-center border border-volt/30">
                <FileText className="w-8 h-8 text-volt" />
              </div>
              <div className="text-volt font-mono text-sm">{fname}</div>
              <div className="text-white/40 text-xs">Contract loaded — ready to analyse</div>
            </div>
          ) : (
            <div className="flex flex-col items-center gap-4">
              <div className="w-20 h-20 rounded-2xl glass flex items-center justify-center border border-white/10 animate-float">
                <Upload className="w-9 h-9 text-white/30" />
              </div>
              <div>
                <p className="text-white/60 font-body">Drop your contract here</p>
                <p className="text-white/25 text-sm font-mono mt-1">.txt · .pdf · .doc · .docx</p>
              </div>
            </div>
          )}
        </div>

        {/* Analyse button */}
        {loaded && (
          <button
            onClick={() => setActiveScreen('analysis')}
            className="mt-6 w-full btn-shimmer rounded-xl py-4 text-white font-display font-bold text-lg flex items-center justify-center gap-3 group"
          >
            <Shield className="w-5 h-5" />
            Analyse Contract
            <ChevronRight className="w-5 h-5 group-hover:translate-x-1 transition-transform" />
          </button>
        )}

        {/* Feature pills */}
        <div className="flex flex-wrap gap-2 justify-center mt-8">
          {['Clause Extraction', 'Risk Scoring', 'Human Gate', 'On-Chain Audit', 'Weilchain MCP'].map(f => (
            <span key={f} className="glass rounded-full px-3 py-1 text-xs font-mono text-white/30">{f}</span>
          ))}
        </div>
      </div>
    </div>
  )
}
