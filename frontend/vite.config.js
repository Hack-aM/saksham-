import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, '')
      },
      '/analyze': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      },
      '/upload': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      },
      '/approve': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      },
      '/health': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      },
      '/events': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      },
      '/history': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      },
      '/connections': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      },
      '/settings': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      }
    }
  }
})
