/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Produces a self-contained server (.next/standalone) for a small Docker image.
  output: "standalone",
  // O proxy do rewrite derruba a conexão em 30s por padrão ("socket hang up",
  // 502 na tela). Ler um processo inteiro com OCR e radar passa disso; o
  // backend espera o motor até 300s (MOTOR_TIMEOUT_MS), e aqui vale o mesmo.
  experimental: { proxyTimeout: 300_000 },
  // Same-origin API: the browser calls /api/* on the frontend, and Next proxies
  // it server-side to the backend over the internal network. No CORS needed.
  async rewrites() {
    const backend = process.env.BACKEND_URL || "http://localhost:8080";
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
};

export default nextConfig;
