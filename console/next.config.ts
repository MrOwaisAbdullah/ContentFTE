import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Avoid Next inferring the wrong workspace root from the parent lockfile.
  outputFileTracingRoot: __dirname,
};

export default nextConfig;