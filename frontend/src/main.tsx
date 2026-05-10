import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import AppGated from './AppGated.tsx'
import { ErrorBoundary } from './components/ErrorBoundary.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <AppGated />
    </ErrorBoundary>
  </StrictMode>,
)
