/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './pages/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
    './app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      fontFamily: {
        display: ['Syne', 'sans-serif'],
        mono:    ['JetBrains Mono', 'monospace'],
        body:    ['DM Sans', 'sans-serif'],
      },
      colors: {
        void:  '#04060F',
        glass: 'rgba(255,255,255,0.04)',
        cyan:  { DEFAULT: '#00F5FF', dim: '#00C4CC' },
        volt:  { DEFAULT: '#8AFF00', dim: '#6DCC00' },
        pink:  { DEFAULT: '#FF2D78', dim: '#CC2460' },
        violet:{ DEFAULT: '#9B5CF6', dim: '#7C3AED' },
      },
      backgroundImage: {
        'mesh-1': 'radial-gradient(ellipse 80% 80% at 20% 20%, rgba(155,92,246,0.15) 0%, transparent 60%)',
        'mesh-2': 'radial-gradient(ellipse 60% 60% at 80% 80%, rgba(0,245,255,0.10) 0%, transparent 60%)',
        'mesh-3': 'radial-gradient(ellipse 50% 50% at 50% 10%, rgba(255,45,120,0.08) 0%, transparent 60%)',
      },
      backdropBlur: { xs: '2px' },
      animation: {
        'pulse-slow':  'pulse 4s cubic-bezier(0.4,0,0.6,1) infinite',
        'float':       'float 6s ease-in-out infinite',
        'scan':        'scan 3s linear infinite',
        'glow':        'glow 2s ease-in-out infinite alternate',
        'shimmer':     'shimmer 2.5s linear infinite',
        'spin-slow':   'spin 8s linear infinite',
      },
      keyframes: {
        float:   { '0%,100%': { transform: 'translateY(0)' }, '50%': { transform: 'translateY(-10px)' } },
        scan:    { '0%': { transform: 'translateY(-100%)' }, '100%': { transform: 'translateY(400%)' } },
        glow:    { '0%': { opacity: 0.4 }, '100%': { opacity: 1 } },
        shimmer: { '0%': { backgroundPosition: '-200% 0' }, '100%': { backgroundPosition: '200% 0' } },
      },
      boxShadow: {
        'glow-cyan':   '0 0 30px rgba(0,245,255,0.3)',
        'glow-violet': '0 0 30px rgba(155,92,246,0.3)',
        'glow-pink':   '0 0 30px rgba(255,45,120,0.3)',
        'glass':       '0 8px 32px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.08)',
      },
    },
  },
  plugins: [],
}
