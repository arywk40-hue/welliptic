const path = require('path')

/** @type {import('next').NextConfig} */
const nextConfig = {
  // Silence "multiple lockfiles" warning — pin workspace root to this UI dir
  outputFileTracingRoot: path.join(__dirname),
  async rewrites() {
    // Only proxy /api/* to backend during development
    if (process.env.NODE_ENV === 'development') {
      return [
        {
          source: '/api/:path*',
          destination: 'http://localhost:8000/api/:path*',
        },
      ]
    }
    return []
  },
}
module.exports = nextConfig

