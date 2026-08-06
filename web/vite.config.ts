import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

/**
 * maplibre-gl 的 worker 會 `import './maplibre-gl-shared.mjs'`。用 ?url 匯入
 * worker 只會複製 worker 檔案本身，它的相依不會跟著走，worker 一啟動就 404，
 * 結果是地圖只剩底圖、GeoJSON 圖層永遠畫不出來（而且完全不報錯）。
 * 這裡把 shared 以「原檔名」放進 assets/，worker 的相對 import 才解析得到。
 */
function maplibreWorkerDeps(): Plugin {
  return {
    name: 'maplibre-worker-deps',
    generateBundle() {
      const src = path.resolve(
        __dirname,
        'node_modules/maplibre-gl/dist/maplibre-gl-shared.mjs',
      )
      this.emitFile({
        type: 'asset',
        fileName: 'assets/maplibre-gl-shared.mjs',
        source: fs.readFileSync(src, 'utf-8'),
      })
    },
  }
}

// https://vite.dev/config/
export default defineConfig({
  base: '/',
  plugins: [react(), tailwindcss(), maplibreWorkerDeps()],
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
