import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    watch: {
      ignored: ['**/src-tauri/target/**']
    },
    proxy: {
      '/api': 'http://127.0.0.1:8110',
      '/ws': {
        target: 'ws://127.0.0.1:8110',
        ws: true
      }
    }
  }
})
