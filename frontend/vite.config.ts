import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// В dev-режиме API и WebSocket проксируются на локальный Django (manage.py runserver / uvicorn :8000)
const backend = process.env.VITE_BACKEND_URL ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  // обработчик тайлов карты собирается отдельным ES-модулем (см. src/map/engine.ts)
  worker: { format: 'es' },
  server: {
    port: 5173,
    proxy: {
      '/api': backend,
      '/admin': backend,
      '/static': backend,
      '/ws': { target: backend.replace(/^http/, 'ws'), ws: true },
    },
  },
})
