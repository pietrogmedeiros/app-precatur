/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Produces a self-contained server (.next/standalone) for a small Docker image.
  output: "standalone",
  // Same-origin API: the browser calls /api/* on the frontend, and Next proxies
  // it server-side to the backend over the internal network. No CORS needed.
  async rewrites() {
    const backend = process.env.BACKEND_URL || "http://localhost:8080";
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
};

export default nextConfig;
