import type { NextConfig } from 'next'

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: '/engine/:path*',
        destination: 'http://localhost:8090/:path*',
      },
    ]
  },
}

export default nextConfig
