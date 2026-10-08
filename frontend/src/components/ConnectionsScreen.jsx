import React, { useState, useEffect } from 'react'
import Card from './Card'
import Badge from './Badge'
import Button from './Button'

/**
 * ConnectionsScreen Component.
 * Displays integration status for Gemini, GitHub, and Render using safe metadata only.
 */
export default function ConnectionsScreen() {
  const [connections, setConnections] = useState(null)
  const [isLoading, setIsLoading] = useState(true)
  const [errorMessage, setErrorMessage] = useState('')

  useEffect(() => {
    let isMounted = true

    async function fetchConnections() {
      try {
        setIsLoading(true)
        setErrorMessage('')
        const response = await fetch('/connections')
        if (!response.ok) {
          throw new Error(`Failed to load connections (Status ${response.status})`)
        }
        const data = await response.json()
        if (isMounted) {
          setConnections(data)
        }
      } catch (err) {
        if (isMounted) {
          setErrorMessage(err.message || 'Could not retrieve connection statuses.')
        }
      } finally {
        if (isMounted) {
          setIsLoading(false)
        }
      }
    }

    fetchConnections()

    return () => {
      isMounted = false
    }
  }, [])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--card-gap)' }}>
      {/* Error Banner */}
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

      {/* Overview Banner */}
      <Card
        title="Service Connections & Integrations"
        subtitle="Saksham integrates with Google Gemini, GitHub, and Render via server environment variables."
      >
        <p style={{ fontSize: '14px', color: 'var(--color-muted)', lineHeight: 1.5 }}>
          For security, credentials and API tokens are configured exclusively through the backend environment (<code style={{ fontFamily: 'var(--font-mono)' }}>.env</code>). Secret values are never sent to or stored in the browser.
        </p>
      </Card>

      {/* Integration Cards Grid */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
        {/* Google Gemini Card */}
        <Card>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '16px', flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', gap: '16px', alignItems: 'flex-start' }}>
              <div
                style={{
                  width: '44px',
                  height: '44px',
                  borderRadius: '10px',
                  backgroundColor: 'var(--color-accent-tint)',
                  color: 'var(--color-accent)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flexShrink: 0,
                }}
              >
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M12 2v20M2 12h20M4.93 4.93l14.14 14.14M4.93 19.07l14.14-14.14" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <h4 style={{ fontSize: '16px', fontWeight: 800, color: 'var(--color-ink)' }}>
                    Google Gemini AI
                  </h4>
                  {connections?.gemini?.configured ? (
                    <Badge variant="success">Configured</Badge>
                  ) : (
                    <Badge variant="medium">Not Configured</Badge>
                  )}
                </div>
                <p style={{ fontSize: '14px', color: 'var(--color-muted)', maxWidth: '600px' }}>
                  {connections?.gemini?.description || 'Powers AI-assisted patch generation and post-deploy runtime diagnosis.'}
                </p>
                <div style={{ fontSize: '13px', color: 'var(--color-muted)', marginTop: '4px' }}>
                  <strong>Configured Model: </strong>
                  <code style={{ fontFamily: 'var(--font-mono)' }}>{connections?.gemini?.model || (isLoading ? 'Loading...' : '—')}</code>
                </div>
              </div>
            </div>

            <div style={{ fontSize: '13px', color: 'var(--color-muted)' }}>
              Variable: <code style={{ fontFamily: 'var(--font-mono)' }}>GEMINI_API_KEY</code>
            </div>
          </div>
        </Card>

        {/* GitHub Card */}
        <Card>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '16px', flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', gap: '16px', alignItems: 'flex-start' }}>
              <div
                style={{
                  width: '44px',
                  height: '44px',
                  borderRadius: '10px',
                  backgroundColor: 'var(--color-accent-tint)',
                  color: 'var(--color-accent)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flexShrink: 0,
                }}
              >
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.87a3.37 3.37 0 0 0-.94-2.61c3.14-.35 6.44-1.54 6.44-7A5.44 5.44 0 0 0 20 4.77 5.07 5.07 0 0 0 19.91 1S18.73.65 16 2.48a13.38 13.38 0 0 0-7 0C6.27.65 5.09 1 5.09 1A5.07 5.07 0 0 0 5 4.77a5.44 5.44 0 0 0-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 0 0 9 18.13V22" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <h4 style={{ fontSize: '16px', fontWeight: 800, color: 'var(--color-ink)' }}>
                    GitHub API
                  </h4>
                  {connections?.github?.configured ? (
                    <Badge variant="success">Configured</Badge>
                  ) : (
                    <Badge variant="medium">Not Configured</Badge>
                  )}
                </div>
                <p style={{ fontSize: '14px', color: 'var(--color-muted)', maxWidth: '600px' }}>
                  {connections?.github?.description || 'Automated new repository creation and clean pre-push commits.'}
                </p>
                <div style={{ fontSize: '13px', color: 'var(--color-muted)', marginTop: '4px' }}>
                  <strong>Required Scopes: </strong>
                  <code style={{ fontFamily: 'var(--font-mono)' }}>repo</code>, <code style={{ fontFamily: 'var(--font-mono)' }}>workflow</code> (Classic PAT)
                </div>
              </div>
            </div>

            <div style={{ fontSize: '13px', color: 'var(--color-muted)' }}>
              Variable: <code style={{ fontFamily: 'var(--font-mono)' }}>GITHUB_TOKEN</code>
            </div>
          </div>
        </Card>

        {/* Render Card */}
        <Card>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '16px', flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', gap: '16px', alignItems: 'flex-start' }}>
              <div
                style={{
                  width: '44px',
                  height: '44px',
                  borderRadius: '10px',
                  backgroundColor: 'var(--color-accent-tint)',
                  color: 'var(--color-accent)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flexShrink: 0,
                }}
              >
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <h4 style={{ fontSize: '16px', fontWeight: 800, color: 'var(--color-ink)' }}>
                    Render Cloud Platform
                  </h4>
                  {connections?.render?.configured ? (
                    <Badge variant="success">Configured</Badge>
                  ) : (
                    <Badge variant="medium">Not Configured</Badge>
                  )}
                </div>
                <p style={{ fontSize: '14px', color: 'var(--color-muted)', maxWidth: '600px' }}>
                  {connections?.render?.description || 'Target cloud deployment platform for hosting FastAPI web services.'}
                </p>
                <div style={{ fontSize: '13px', color: 'var(--color-muted)', marginTop: '4px' }}>
                  <strong>Deployment Type: </strong> Web Service (FastAPI)
                </div>
              </div>
            </div>

            <div style={{ fontSize: '13px', color: 'var(--color-muted)' }}>
              Variable: <code style={{ fontFamily: 'var(--font-mono)' }}>RENDER_API_KEY</code>
            </div>
          </div>
        </Card>
      </div>
    </div>
  )
}
