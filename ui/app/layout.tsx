import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'LexAudit — AI Legal Contract Reviewer',
  description: 'Auditable AI legal contract analysis on Weilchain',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="noise antialiased min-h-screen bg-void">
        {/* Ambient background meshes */}
        <div className="fixed inset-0 pointer-events-none z-0">
          <div className="absolute inset-0 bg-mesh-1 animate-pulse-slow" />
          <div className="absolute inset-0 bg-mesh-2 animate-pulse-slow" style={{ animationDelay: '2s' }} />
          <div className="absolute inset-0 bg-mesh-3 animate-pulse-slow" style={{ animationDelay: '4s' }} />
          {/* Grid overlay */}
          <div className="absolute inset-0 opacity-[0.03]"
            style={{ backgroundImage: 'linear-gradient(rgba(0,245,255,1) 1px, transparent 1px), linear-gradient(90deg, rgba(0,245,255,1) 1px, transparent 1px)', backgroundSize: '60px 60px' }} />
        </div>
        <div className="relative z-10">
          {children}
        </div>
      </body>
    </html>
  )
}
