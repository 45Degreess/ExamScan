import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Same proxy contract as examscan-ui/vite.config.js — both UIs talk to the
// same FastAPI backend (software/scanner_api.py) on port 8000.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': { target: 'http://localhost:8000', rewrite: (p) => p.replace(/^\/api/, '') }
    }
  }
})
