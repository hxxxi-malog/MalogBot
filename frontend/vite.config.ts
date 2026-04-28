import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import { fileURLToPath, URL } from 'node:url'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    vue(),
    tailwindcss(),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  server: {
    port: 5173,
    proxy: {
      '/sessions': 'http://localhost:5000',
      '/chat': 'http://localhost:5000',
      '/stop': 'http://localhost:5000',
      '/confirm': 'http://localhost:5000',
      '/cancel': 'http://localhost:5000',
      '/continue': 'http://localhost:5000',
      '/onboarding': 'http://localhost:5000',
      '/web-search': 'http://localhost:5000',
      '/knowledge-bases': 'http://localhost:5000',
      '/documents': 'http://localhost:5000',
      '/mcp': 'http://localhost:5000',
      '/team': 'http://localhost:5000',
      '/api': 'http://localhost:5000',  // 研究相关 API
    }
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  }
})
