import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import AppGated from './AppGated.tsx'
import AdminApp from './admin/AdminApp.tsx'
import { ErrorBoundary } from './components/ErrorBoundary.tsx'

// Simple path-based routing — only two top-level surfaces today (the
// evaluator chat at /, the operator dashboard at /admin), so a single
// switch beats pulling in a router. The admin tree is fully gated and
// has its own auth surface; the public chat tree mounts only when the
// pathname is anything else.
const isAdminRoute = window.location.pathname.startsWith('/admin')

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      {isAdminRoute ? <AdminApp /> : <AppGated />}
    </ErrorBoundary>
  </StrictMode>,
)
