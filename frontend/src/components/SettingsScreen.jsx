import React, { useState, useEffect } from 'react'
import Card from './Card'
import Badge from './Badge'

/**
 * SettingsScreen Component.
 * Displays non-sensitive application settings, security policies, and scoring weights.
 */
export default function SettingsScreen() {
  const [settings, setSettings] = useState(null)
  const [isLoading, setIsLoading] = useState(true)
  const [errorMessage, setErrorMessage] = useState('')

  useEffect(() => {
    let isMounted = true

    async function fetchSettings() {
      try {
        setIsLoading(true)
        setErrorMessage('')
        const response = await fetch('/settings')
        if (!response.ok) {
          throw new Error(`Failed to load settings (Status ${response.status})`)
        }
        const data = await response.json()
        if (isMounted) {
          setSettings(data)
        }
      } catch (err) {
        if (isMounted) {
          setErrorMessage(err.message || 'Could not retrieve settings.')
        }
      } finally {
        if (isMounted) {
          setIsLoading(false)
        }
      }
    }

    fetchSettings()

    return () => {
      isMounted = false
    }
  }, [])

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

      {/* App & Operational Configuration */}
      <Card title="Operational Settings" subtitle="Server configuration, resource limits, and sandbox parameters.">
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '16px' }}>
          <div className="selected-file-box" style={{ flexDirection: 'column', alignItems: 'flex-start', gap: '4px' }}>
            <span style={{ fontSize: '12px', color: 'var(--color-muted)', fontWeight: 700, textTransform: 'uppercase' }}>
              Environment Mode
            </span>
            <span style={{ fontSize: '16px', fontWeight: 800, color: 'var(--color-ink)' }}>
              {settings?.environment || 'development'}
            </span>
          </div>

          <div className="selected-file-box" style={{ flexDirection: 'column', alignItems: 'flex-start', gap: '4px' }}>
            <span style={{ fontSize: '12px', color: 'var(--color-muted)', fontWeight: 700, textTransform: 'uppercase' }}>
              Max Archive Size
            </span>
            <span style={{ fontSize: '16px', fontWeight: 800, color: 'var(--color-ink)' }}>
              {settings?.max_upload_size_mb || 25} MB
            </span>
          </div>

          <div className="selected-file-box" style={{ flexDirection: 'column', alignItems: 'flex-start', gap: '4px' }}>
            <span style={{ fontSize: '12px', color: 'var(--color-muted)', fontWeight: 700, textTransform: 'uppercase' }}>
              Workspace Retention
            </span>
            <span style={{ fontSize: '16px', fontWeight: 800, color: 'var(--color-ink)' }}>
              {settings?.workspace_ttl_seconds ? `${settings.workspace_ttl_seconds / 60} minutes` : '60 minutes'}
            </span>
          </div>

          <div className="selected-file-box" style={{ flexDirection: 'column', alignItems: 'flex-start', gap: '4px' }}>
            <span style={{ fontSize: '12px', color: 'var(--color-muted)', fontWeight: 700, textTransform: 'uppercase' }}>
              Secret Scanner
            </span>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span style={{ fontSize: '16px', fontWeight: 800, color: 'var(--color-ink)' }}>
                Gitleaks CLI
              </span>
              <Badge variant="success">Active</Badge>
            </div>
          </div>
        </div>
      </Card>

      {/* Deploy Readiness Scoring Weights */}
      <Card
        title="Deploy Readiness Scoring Rules"
        subtitle="Deterministic score calculation parameters per PRD and ARCHITECTURE specifications."
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <p style={{ fontSize: '14px', color: 'var(--color-muted)', lineHeight: 1.5 }}>
            Each analyzed project begins with a baseline score of <strong>100</strong>. Points are deducted based on detected issue severities:
          </p>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '12px' }}>
            <div style={{ background: 'var(--color-high-bg)', padding: '12px 16px', borderRadius: '8px', border: '1px solid #F5C6CB' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ color: 'var(--color-high-text)', fontWeight: 800, fontSize: '14px' }}>HIGH SEVERITY</span>
                <span style={{ color: 'var(--color-high-text)', fontWeight: 800, fontSize: '18px' }}>-30 pts</span>
              </div>
              <p style={{ fontSize: '12px', color: 'var(--color-high-text)', marginTop: '4px' }}>
                Active API keys, hardcoded secrets, and secret leaks in git history. Blocks deployment.
              </p>
            </div>

            <div style={{ background: 'var(--color-med-bg)', padding: '12px 16px', borderRadius: '8px', border: '1px solid #FFE8A1' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ color: 'var(--color-med-text)', fontWeight: 800, fontSize: '14px' }}>MEDIUM SEVERITY</span>
                <span style={{ color: 'var(--color-med-text)', fontWeight: 800, fontSize: '18px' }}>-15 pts</span>
              </div>
              <p style={{ fontSize: '12px', color: 'var(--color-med-text)', marginTop: '4px' }}>
                Missing .gitignore entry for .env, hardcoded 127.0.0.1 host binds, wrong port configurations.
              </p>
            </div>

            <div style={{ background: 'var(--color-bg)', padding: '12px 16px', borderRadius: '8px', border: '1px solid var(--color-border)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ color: 'var(--color-ink)', fontWeight: 800, fontSize: '14px' }}>LOW SEVERITY</span>
                <span style={{ color: 'var(--color-ink)', fontWeight: 800, fontSize: '18px' }}>-5 pts</span>
              </div>
              <p style={{ fontSize: '12px', color: 'var(--color-muted)', marginTop: '4px' }}>
                Debug mode enabled in production code, untracked junk/temporary files.
              </p>
            </div>
          </div>
        </div>
      </Card>

      {/* Application Information */}
      <Card title="About Saksham" subtitle="Pre-Push Safety & Deploy Agent for FastAPI student developers.">
        <p style={{ fontSize: '14px', color: 'var(--color-muted)', lineHeight: 1.5 }}>
          Built for hackathon deployment reliability. Provides pre-push secret audits, unified diff approvals, isolated GitHub repository initialization, Render cloud hosting, and automated self-repair health loops.
        </p>
        <div style={{ fontSize: '13px', color: 'var(--color-muted)', marginTop: '12px', paddingTop: '12px', borderTop: '1px solid var(--color-border)' }}>
          Saksham MVP Version 0.1.0 • Built with Python 3.11, FastAPI, React, and Vite.
        </div>
      </Card>
    </div>
  )
}
