import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // Browser code always calls relative /v1 URLs. This development-only proxy
  // mirrors the same-origin routing an ingress or web server provides in
  // production without weakening the API with broad CORS permissions.
  server: {
    proxy: {
      '/v1': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
