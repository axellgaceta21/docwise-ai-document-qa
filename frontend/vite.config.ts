import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')
  return {
    plugins: [react()],
    define: { 'globalThis.__DOCWISE_API_BASE_URL__': JSON.stringify(env.VITE_API_BASE_URL || '') },
    server: { proxy: { '/api': env.VITE_API_TARGET || 'http://127.0.0.1:8000' } },
  }
})
