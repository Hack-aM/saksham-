import React, { useState, useEffect } from 'react'
import Card from './Card'
import Button from './Button'
import Badge from './Badge'

/**
 * HistoryScreen Component.
 * Fetches and displays past analysis and deployment records from SQLite database.
 */
export default function HistoryScreen({ onNavigateToNewDeploy }) {
  const [historyData, setHistoryData] = useState({ analyses: [], deployments: [] })
  const [activeTab, setActiveTab] = useState('all') // 'all' | 'deployments' | 'analyses'
  const [isLoading, setIsLoading] = useState(true)
  const [errorMessage, setErrorMessage] = useState('')

  useEffect(() => {
    let isMounted = true

    async function fetchHistory() {
      try {
        setIsLoading(true)
        setErrorMessage('')
        const response = await fetch('/history')
        if (!response.ok) {
          throw new Error(`Failed to load history (Status ${response.status})`)
        }
        const data = await response.json()
        if (isMounted) {
          setHistoryData(data)
        }
      } catch (err) {
        if (isMounted) {
          setErrorMessage(err.message || 'Could not retrieve deployment history.')
        }
      } finally {
        if (isMounted) {
          setIsLoading(false)
        }
      }
    }

    fetchHistory()

    return () => {
      isMounted = false
    }
  }, [])

  const { analyses = [], deployments = [] } = historyData

  const totalRuns = analyses.length + deployments.length
  const isEmpty = totalRuns === 0

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--card-gap)' }}>
      {/* Error Alert */}
      {errorMessage && (
        <div className="alert-banner alert-banner-danger" role="alert">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ flexShrink: 0 }}>
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="8" x2="12" y2="12" />
            <line x1="12" y1="16" x2="12.01" y2="16" />
          </svg>
          <div>
            <strong>Error: </strong>
            <span>{errorMessage}</span>
          </div>
        </div>
      )}

      {/* Main History Card */}
      <Card
        title="Deployment & Analysis History"
        subtitle="Review past project scans, safety scores, and Render cloud deployments."
        headerAction={
          !isEmpty && (
            <div style={{ display: 'flex', gap: '8px' }}>
              <button
                type="button"
                className={`filter-pill-btn ${activeTab === 'all' ? 'active' : ''}`}
                onClick={() => setActiveTab('all')}
              >
                All ({totalRuns})
              </button>
              <button
                type="button"
                className={`filter-pill-btn ${activeTab === 'deployments' ? 'active' : ''}`}
                onClick={() => setActiveTab('deployments')}
              >
                Deployments ({deployments.length})
              </button>
              <button
                type="button"
                className={`filter-pill-btn ${activeTab === 'analyses' ? 'active' : ''}`}
                onClick={() => setActiveTab('analyses')}
              >
                Analyses ({analyses.length})
              </button>
            </div>
          )
        }
      >
        {isLoading ? (
          <div style={{ textAlign: 'center', padding: '40px 0', color: 'var(--color-muted)' }}>
            <span className="spinner spinner-teal" style={{ width: '24px', height: '24px', marginBottom: '8px' }}></span>
            <p>Loading history records...</p>
          </div>
        ) : isEmpty ? (
          <div style={{ textAlign: 'center', padding: '48px 20px' }}>
            <div
              style={{
                width: '48px',
                height: '48px',
                borderRadius: '50%',
                backgroundColor: 'var(--color-accent-tint)',
                color: 'var(--color-accent)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                margin: '0 auto 16px',
              }}
            >
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="9" />
                <path d="M12 7v5l3 3" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
            <h4 style={{ fontSize: '16px', fontWeight: 800, color: 'var(--color-ink)', marginBottom: '8px' }}>
              No deployments yet
            </h4>
            <p style={{ fontSize: '14px', color: 'var(--color-muted)', maxWidth: '420px', margin: '0 auto 20px' }}>
              You haven't run any analysis or deployment sessions yet. Upload your first FastAPI project archive to get started.
            </p>
            <Button variant="primary" onClick={onNavigateToNewDeploy}>
              Deploy your first project
            </Button>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            {/* Deployments Section */}
            {(activeTab === 'all' || activeTab === 'deployments') && deployments.length > 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                <h4 style={{ fontSize: '14px', fontWeight: 800, color: 'var(--color-ink)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                  Live Deployments
                </h4>
                {deployments.map((dep) => (
                  <div key={dep.id} className="selected-file-box" style={{ padding: '16px' }}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', minWidth: 0 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span style={{ fontWeight: 800, fontSize: '15px', color: 'var(--color-ink)' }}>
                          {dep.project_name || 'FastAPI Service'}
                        </span>
                        <Badge variant="success">{dep.health_status || '200 OK'}</Badge>
                        <Badge variant="neutral">Score {dep.final_score}/100</Badge>
                      </div>
                      <div style={{ fontSize: '13px', color: 'var(--color-muted)' }}>
                        <span>Platform: {dep.platform || 'Render'} • </span>
                        <span>{new Date(dep.created_at).toLocaleString()}</span>
                      </div>
                      <a
                        href={dep.live_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="link-url-text"
                        style={{ marginTop: '2px' }}
                      >
                        {dep.live_url}
                      </a>
                    </div>
                    <Button
                      variant="secondary"
                      style={{ minHeight: '36px', padding: '0 12px', fontSize: '13px' }}
                      onClick={() => window.open(dep.live_url, '_blank')}
                    >
                      Open app
                    </Button>
                  </div>
                ))}
              </div>
            )}

            {/* Analyses Section */}
            {(activeTab === 'all' || activeTab === 'analyses') && analyses.length > 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginTop: deployments.length > 0 ? '16px' : 0 }}>
                <h4 style={{ fontSize: '14px', fontWeight: 800, color: 'var(--color-ink)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                  Pre-Push Scans
                </h4>
                {analyses.map((ana) => (
                  <div key={ana.id} className="selected-file-box" style={{ padding: '16px' }}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', minWidth: 0 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span style={{ fontWeight: 800, fontSize: '15px', color: 'var(--color-ink)' }}>
                          {ana.project_name || 'Project'}
                        </span>
                        <Badge variant={ana.score >= 80 ? 'success' : 'high'}>
                          Score {ana.score}/100
                        </Badge>
                      </div>
                      <div style={{ fontSize: '13px', color: 'var(--color-muted)' }}>
                        <span>Stack: {ana.stack || 'FastAPI'} • </span>
                        <span>{new Date(ana.created_at).toLocaleString()}</span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </Card>
    </div>
  )
}
