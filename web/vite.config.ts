import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// https://vite.dev/config/
export default defineConfig({
  base: '/',
  plugins: [react(), tailwindcss()],
  // maplibre-gl v6 的 worker 是 ES module；Vite 預設把 worker 打成 iife，
  // 會讓 maplibre-gl-worker 載入失敗（net::ERR_FAILED）。worker 一掛，
  // GeoJSON source 永遠不會 ready，地圖只剩底圖、站點畫不出來。
  worker: { format: 'es' },
  optimizeDeps: { exclude: ['maplibre-gl'] },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
  },
})
