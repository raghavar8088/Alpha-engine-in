import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/engine/:path*",
        destination: `${process.env.INTERNAL_API_URL || "http://127.0.0.1:8090"}/:path*`,
      },
    ];
  },
};

export default nextConfig;
