import { useEffect, useState } from 'react'

import { fetchHealth, type ComponentStatus, type Health } from './api/health'

const REFRESH_INTERVAL_MS = 15_000

type HealthState =
  | { kind: 'loading' }
  | { kind: 'loaded'; health: Health; checkedAt: Date }
  | { kind: 'failed'; message: string; checkedAt: Date }

function StatusBadge({ status }: { status: ComponentStatus }) {
  return <span className={`badge badge-${status}`}>{status === 'ok' ? 'OK' : 'Error'}</span>
}

function HealthDetails({ state }: { state: HealthState }) {
  switch (state.kind) {
    case 'loading':
      return <p className="muted">Checking…</p>
    case 'failed':
      return (
        <p className="error" role="alert">
          Cannot reach the API: {state.message}
        </p>
      )
    case 'loaded':
      return (
        <dl className="components">
          <dt>Database (TimescaleDB)</dt>
          <dd>
            <StatusBadge status={state.health.db} />
          </dd>
          <dt>Redis</dt>
          <dd>
            <StatusBadge status={state.health.redis} />
          </dd>
        </dl>
      )
  }
}

export default function App() {
  const [state, setState] = useState<HealthState>({ kind: 'loading' })
  const [refreshCount, setRefreshCount] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    fetchHealth(controller.signal).then(
      (health) => {
        setState({ kind: 'loaded', health, checkedAt: new Date() })
      },
      (error: unknown) => {
        if (controller.signal.aborted) return
        const message = error instanceof Error ? error.message : String(error)
        setState({ kind: 'failed', message, checkedAt: new Date() })
      },
    )
    const timer = setTimeout(() => {
      setRefreshCount((count) => count + 1)
    }, REFRESH_INTERVAL_MS)
    return () => {
      controller.abort()
      clearTimeout(timer)
    }
  }, [refreshCount])

  return (
    <main className="page">
      <header>
        <h1>NetOps Platform</h1>
        <p className="muted">Campus network management, monitoring and fault diagnosis</p>
      </header>

      <section className="card" aria-labelledby="health-title">
        <div className="card-header">
          <h2 id="health-title">System health</h2>
          <button
            type="button"
            onClick={() => {
              setRefreshCount((count) => count + 1)
            }}
          >
            Refresh
          </button>
        </div>
        <HealthDetails state={state} />
        {state.kind !== 'loading' && (
          <p className="muted small">
            Last checked {state.checkedAt.toLocaleTimeString()}
            {state.kind === 'loaded' && ` · API v${state.health.version}`}
          </p>
        )}
      </section>
    </main>
  )
}
