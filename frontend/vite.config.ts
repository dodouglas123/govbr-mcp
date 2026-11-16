import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const upstream = process.env.GOVBR_DEV_UPSTREAM ?? 'http://127.0.0.1:8000'
export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': upstream, '/readyz': upstream, '/healthz': upstream, '/mcp': upstream, '/.well-known': upstream } },
  preview: { proxy: { '/api': upstream, '/readyz': upstream, '/healthz': upstream, '/mcp': upstream, '/.well-known': upstream } },
})
