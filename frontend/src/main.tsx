import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { invoke } from '@tauri-apps/api/core'
import App, { configureRuntime } from './App'
import './styles.css'

async function bootstrap() {
  try {
    const [port, instanceId] = await Promise.all([
      invoke<number>('runtime_backend_port'),
      invoke<string>('runtime_instance_id')
    ])
    configureRuntime(port, instanceId)
  } catch {
    // Browser-only development keeps the historical localhost:8110 fallback.
    configureRuntime(8110, 'development')
  }

  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>
  )
}

void bootstrap()
