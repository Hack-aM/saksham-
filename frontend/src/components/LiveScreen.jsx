import React, { useState, useEffect, useRef } from 'react'
import Card from './Card'
import Button from './Button'
import Badge from './Badge'

const MAX_RECONNECT_ATTEMPTS = 3

/**
 * LiveScreen Component for Step 4 of the Saksham Pipeline.
 * Connects to the backend SSE endpoint (GET /events/{run_id}) using native EventSource,
 * displaying real-time checklist progress, terminal logs, self-fix iterations,
 * and live deployment URLs.
 */
export default function LiveScreen({
  runId,
  projectName = 'Project',
  initialScore,
  repoConfig,
  onDeployAnother,
}) {
  const [events, setEvents] = useState([])
  const [connectionStatus, setConnectionStatus] = useState('connecting') // 'connecting' | 'connected' | 'closed' | 'error'
  const [isComplete, setIsComplete] = useState(false)
  const [isFailed, setIsFailed] = useState(false)
  const [errorMessage, setErrorMessage] = useState('')
  const [liveUrl, setLiveUrl] = useState('')
  const [repoUrl, setRepoUrl] = useState('')
  const [finalScore, setFinalScore] = useState(null)

  const logConsoleRef = useRef(null)
  const eventSourceRef = useRef(null)
  const reconnectCountRef = useRef(0)

  // Auto-scroll log console
  useEffect(() => {
    if (logConsoleRef.current) {
      logConsoleRef.current.scrollTop = logConsoleRef.current.scrollHeight
    }
  }, [events])

  // Establish and manage SSE EventSource connection
  useEffect(() => {
    if (!runId) {
      setConnectionStatus('error')
      setErrorMessage('No valid Run ID available for streaming.')
      return
    }

    let isMounted = true

    const connectSSE = () => {
      try {
        const es = new EventSource(`/events/${runId}`)
        eventSourceRef.current = es

        es.onopen = () => {
          if (!isMounted) return
          setConnectionStatus('connected')
          reconnectCountRef.current = 0
        }

        es.onmessage = (event) => {
          if (!isMounted) return

          try {
            const data = JSON.parse(event.data)
            setEvents((prev) => [...prev, data])

            // Extract URLs or results if present in details
            if (data.details) {
              if (data.details.live_url) setLiveUrl(data.details.live_url)
              if (data.details.repo_url) setRepoUrl(data.details.repo_url)
              if (data.details.final_score !== undefined) setFinalScore(data.details.final_score)
            }

            // Handle Terminal Stages
            if (data.stage === 'complete' || (data.stage === 'verify' && data.status === 'completed')) {
              setIsComplete(true)
              setConnectionStatus('closed')
              es.close()
            } else if (data.stage === 'error' || data.status === 'failed' || data.status === 'blocked') {
              setIsFailed(true)
              setErrorMessage(data.message || 'Pipeline failed during execution.')
              setConnectionStatus('closed')
              es.close()
            }
          } catch (parseErr) {
            console.warn('Failed to parse SSE event:', parseErr)
          }
        }

        es.onerror = () => {
          if (!isMounted) return

          es.close()
          if (isComplete || isFailed) {
            setConnectionStatus('closed')
            return
          }

          if (reconnectCountRef.current < MAX_RECONNECT_ATTEMPTS) {
            reconnectCountRef.current += 1
            setConnectionStatus('connecting')
            setTimeout(() => {
              if (isMounted && !isComplete && !isFailed) {
                connectSSE()
              }
            }, 2000)
          } else {
            setConnectionStatus('error')
            if (!errorMessage) {
              setErrorMessage('Lost connection to live event stream. Pipeline may still be executing.')
            }
          }
        }
      } catch (err) {
        if (isMounted) {
          setConnectionStatus('error')
          setErrorMessage(err.message || 'Could not open event stream.')
        }
      }
    }

    connectSSE()

    return () => {
      isMounted = false
      if (eventSourceRef.current) {
        eventSourceRef.current.close()
      }
    }
  }, [runId, isComplete, isFailed])

  // Derive Pipeline Stage Statuses for Checklist
  const getStageStatus = (stageKeys) => {
    const matchingEvents = events.filter((e) => stageKeys.includes(e.stage))
    if (matchingEvents.length === 0) return 'pending'

    const lastEvent = matchingEvents[matchingEvents.length - 1]
    if (lastEvent.status === 'failed' || lastEvent.status === 'blocked') return 'failed'
    if (lastEvent.status === 'completed') return 'completed'
    return 'in_progress'
  }

  const auditStatus = getStageStatus(['upload', 'scan', 'audit'])
  const patchStatus = getStageStatus(['fix', 'approve'])
  const githubStatus = getStageStatus(['github'])
  const deployStatus = getStageStatus(['deploy'])
  const verifyStatus = getStageStatus(['verify', 'self_fix'])

  // Helper for checklist icon & status badge
  const renderStatusBadge = (status, successLabel = 'Done') => {
    if (status === 'completed') return <Badge variant="success">{successLabel}</Badge>
    if (status === 'in_progress') {
      return (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', fontSize: '12px', color: 'var(--color-accent)', fontWeight: 700 }}>
          <span className="spinner spinner-teal" style={{ width: '12px', height: '12px' }}></span>
          <span>Running...</span>
        </span>
      )
    }
    if (status === 'failed') return <Badge variant="high">Failed</Badge>
    return <Badge variant="neutral">Pending</Badge>
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--card-gap)' }}>
      {/* Error / Alert Banner */}
      {isFailed && (
        <div className="alert-banner alert-banner-danger" role="alert">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ flexShrink: 0 }}>
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="8" x2="12" y2="12" />
            <line x1="12" y1="16" x2="12.01" y2="16" />
          </svg>
          <div>
            <strong>Deployment Stopped: </strong>
            <span>{errorMessage}</span>
          </div>
        </div>
      )}

      {/* Terminal Success State Banner */}
      {isComplete && (
        <div className="alert-banner alert-banner-success" role="status">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ flexShrink: 0 }}>
            <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" strokeLinecap="round" strokeLinejoin="round" />
            <polyline points="22 4 12 14.01 9 11.01" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <div>
            <strong>Success: </strong>
            <span>
              <strong>{projectName}</strong> is live on Render and passed automated health checks.
            </span>
          </div>
        </div>
      )}

      {/* Deployment & Pipeline Checklist Card */}
      <Card
        title="Deployment Pipeline"
        subtitle={`Run ID: ${runId} • Real-time pipeline status from Server-Sent Events`}
        headerAction={
          connectionStatus === 'connected' ? (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', fontSize: '13px', color: 'var(--color-accent-text)', fontWeight: 600 }}>
              <span className="pulse-dot"></span>
              Live stream active
            </span>
          ) : (
            <Badge variant="neutral">{connectionStatus}</Badge>
          )
        }
      >
        <div className="live-checklist">
          {/* Step 1: Pre-push audit */}
          <div className="checklist-row">
            <div className="checklist-label-group">
              <div className="checklist-icon" style={{ backgroundColor: auditStatus === 'completed' ? 'var(--color-success-tint)' : 'var(--color-bg)' }}>
                {auditStatus === 'completed' ? '✓' : '1'}
              </div>
              <div>
                <h4 className="checklist-title">1. Pre-Push Security Audit</h4>
                <p className="checklist-subtitle">Scan files, git history, and configuration checks</p>
              </div>
            </div>
            {renderStatusBadge(auditStatus)}
          </div>

          {/* Step 2: Patch application */}
          <div className="checklist-row">
            <div className="checklist-label-group">
              <div className="checklist-icon" style={{ backgroundColor: patchStatus === 'completed' ? 'var(--color-success-tint)' : 'var(--color-bg)' }}>
                {patchStatus === 'completed' ? '✓' : '2'}
              </div>
              <div>
                <h4 className="checklist-title">2. Approved Patch Application</h4>
                <p className="checklist-subtitle">Apply approved fixes and re-verify secret gate</p>
              </div>
            </div>
            {renderStatusBadge(patchStatus)}
          </div>

          {/* Step 3: GitHub push */}
          <div className="checklist-row">
            <div className="checklist-label-group">
              <div className="checklist-icon" style={{ backgroundColor: githubStatus === 'completed' ? 'var(--color-success-tint)' : 'var(--color-bg)' }}>
                {githubStatus === 'completed' ? '✓' : '3'}
              </div>
              <div>
                <h4 className="checklist-title">3. GitHub Repository Creation & Push</h4>
                <p className="checklist-subtitle">Create clean remote repo ({repoConfig?.repoName || projectName})</p>
              </div>
            </div>
            {renderStatusBadge(githubStatus)}
          </div>

          {/* Step 4: Render deploy */}
          <div className="checklist-row">
            <div className="checklist-label-group">
              <div className="checklist-icon" style={{ backgroundColor: deployStatus === 'completed' ? 'var(--color-success-tint)' : 'var(--color-bg)' }}>
                {deployStatus === 'completed' ? '✓' : '4'}
              </div>
              <div>
                <h4 className="checklist-title">4. Render Web Service Deployment</h4>
                <p className="checklist-subtitle">Provision cloud service and trigger build</p>
              </div>
            </div>
            {renderStatusBadge(deployStatus)}
          </div>

          {/* Step 5: Verification & Self-Fix */}
          <div className="checklist-row">
            <div className="checklist-label-group">
              <div className="checklist-icon" style={{ backgroundColor: verifyStatus === 'completed' ? 'var(--color-success-tint)' : 'var(--color-bg)' }}>
                {verifyStatus === 'completed' ? '✓' : '5'}
              </div>
              <div>
                <h4 className="checklist-title">5. Health Verification & Auto Self-Fix</h4>
                <p className="checklist-subtitle">HTTP health verification with bounded self-repair loop</p>
              </div>
            </div>
            {renderStatusBadge(verifyStatus, '200 OK')}
          </div>
        </div>
      </Card>

      {/* Live URLs & Output Card (if live or completed) */}
      {(isComplete || liveUrl || repoUrl) && (
        <div className="links-grid">
          <div className="link-card">
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: '12px', color: 'var(--color-muted)', fontWeight: 600 }}>LIVE SERVICE URL</div>
              <a
                href={liveUrl || `https://${projectName.toLowerCase()}.onrender.com`}
                target="_blank"
                rel="noopener noreferrer"
                className="link-url-text"
              >
                {liveUrl || `https://${projectName.toLowerCase()}.onrender.com`}
              </a>
            </div>
            <Button
              variant="primary"
              onClick={() => window.open(liveUrl || `https://${projectName.toLowerCase()}.onrender.com`, '_blank')}
            >
              Open live app
            </Button>
          </div>

          <div className="link-card">
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: '12px', color: 'var(--color-muted)', fontWeight: 600 }}>GITHUB REPOSITORY</div>
              <a
                href={repoUrl || `https://github.com/user/${repoConfig?.repoName || projectName}`}
                target="_blank"
                rel="noopener noreferrer"
                className="link-url-text"
              >
                {repoUrl || `https://github.com/user/${repoConfig?.repoName || projectName}`}
              </a>
            </div>
            <Button
              variant="secondary"
              onClick={() => window.open(repoUrl || `https://github.com/user/${repoConfig?.repoName || projectName}`, '_blank')}
            >
              View repo
            </Button>
          </div>
        </div>
      )}

      {/* Real-time Streaming Event Log Card */}
      <Card
        title="Deployment & Verification Logs"
        subtitle="Live streaming logs from Saksham agent"
      >
        <div className="live-log-console" ref={logConsoleRef} role="log" aria-live="polite">
          {events.length === 0 ? (
            <div style={{ color: '#6E7681', fontStyle: 'italic' }}>
              Waiting for events from /events/{runId}...
            </div>
          ) : (
            events.map((evt, idx) => {
              const dateStr = evt.timestamp
                ? new Date(evt.timestamp * 1000).toLocaleTimeString()
                : new Date().toLocaleTimeString()

              let stageClass = 'log-stage'
              if (evt.stage === 'error' || evt.status === 'failed') stageClass += ' log-stage-error'
              if (evt.stage === 'complete' || evt.status === 'completed') stageClass += ' log-stage-success'
              if (evt.stage === 'self_fix') stageClass += ' log-stage-self_fix'

              return (
                <div key={idx} className="log-entry">
                  <span className="log-timestamp">[{dateStr}]</span>
                  <span className={stageClass}>{evt.stage}</span>
                  <span className="log-message">{evt.message}</span>
                </div>
              )
            })
          )}
        </div>

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '16px' }}>
          <div style={{ fontSize: '13px', color: 'var(--color-muted)' }}>
            {events.length} event(s) recorded • Zero secrets logged
          </div>

          <Button variant="secondary" onClick={onDeployAnother}>
            Deploy another project
          </Button>
        </div>
      </Card>
    </div>
  )
}
