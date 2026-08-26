import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // The web build calls the API from the browser; nothing is proxied and no
  // secrets exist here. The API origin is public configuration.
  env: {},
};

export default nextConfig;
