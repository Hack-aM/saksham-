import React, { useState, useEffect } from 'react'
import Sidebar from './components/Sidebar'
import Header from './components/Header'
import UploadScreen from './components/UploadScreen'
import AuditScreen from './components/AuditScreen'
import LiveScreen from './components/LiveScreen'
import HistoryScreen from './components/HistoryScreen'
import ConnectionsScreen from './components/ConnectionsScreen'
import SettingsScreen from './components/SettingsScreen'
import LoginScreen from './components/LoginScreen'
import Card from './components/Card'
import Button from './components/Button'

export default function App() {
  const getIsLoginRoute = () => {
    if (typeof window === 'undefined') return false
    const p = window.location.pathname.toLowerCase()
    const h = window.location.hash.toLowerCase()
    return p === '/login' || p.endsWith('/login') || h === '#/login' || h === '#login'
  }

  const [isLoginRoute, setIsLoginRoute] = useState(getIsLoginRoute)
  const [currentUser, setCurrentUser] = useState(null)
  const [activeNav, setActiveNav] = useState('new-deploy') // 'new-deploy' | 'history' | 'connections' | 'settings'
  const [currentStep, setCurrentStep] = useState(1)
  const [analysisResult, setAnalysisResult] = useState(null)
  const [repoConfig, setRepoConfig] = useState(null)

  useEffect(() => {
    // Check active authenticated session
    fetch('/auth/me', { credentials: 'include' })
      .then((res) => (res.ok ? res.json() : null))
      .then((user) => {
        if (user) setCurrentUser(user)
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    const handleLocationChange = () => {
      setIsLoginRoute(getIsLoginRoute())
    }
    window.addEventListener('popstate', handleLocationChange)
    window.addEventListener('hashchange', handleLocationChange)
    return () => {
      window.removeEventListener('popstate', handleLocationChange)
      window.removeEventListener('hashchange', handleLocationChange)
    }
  }, [])

  const handleNavigateToLogin = () => {
    if (window.location.pathname !== '/login') {
      window.history.pushState({}, '', '/login')
    }
    setIsLoginRoute(true)
  }

  const handleNavigateHome = () => {
    if (window.location.pathname !== '/') {
      window.history.pushState({}, '', '/')
    }
    setIsLoginRoute(false)
  }

  const handleAnalyzeSuccess = (result, config) => {
    setAnalysisResult(result)
    setRepoConfig(config)
    setCurrentStep(2) // Move to Step 2: Audit
  }

  const handleResetRun = () => {
    setAnalysisResult(null)
    setRepoConfig(null)
    setCurrentStep(1)
    setActiveNav('new-deploy')
  }

  const handleProceedToFix = () => {
    setCurrentStep(3) // Move to Step 3: Fix
  }

  const [isApproving, setIsApproving] = useState(false)
  const [approveError, setApproveError] = useState('')

  const handleProceedToDeploy = async () => {
    if (!analysisResult) return
    setIsApproving(true)
    setApproveError('')

    try {
      const allPatchIds = (analysisResult.patches || []).map((p) => p.id).filter(Boolean)
      const targetRunId = analysisResult.run_id || analysisResult.id

      const response = await fetch('/approve', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          run_id: targetRunId,
          approved_patch_ids: allPatchIds,
          repo_name: repoConfig?.repoName || analysisResult.project_name,
          visibility: repoConfig?.visibility || 'private',
        }),
      })

      if (!response.ok) {
        let errDetail = `Approval failed with status ${response.status}`
        try {
          const errData = await response.json()
          if (errData.detail) errDetail = typeof errData.detail === 'string' ? errData.detail : JSON.stringify(errData.detail)
        } catch {}
        throw new Error(errDetail)
      }

      const approveData = await response.json()
      if (approveData.status === 'blocked') {
        setApproveError(approveData.message || 'Push blocked: unresolved secrets remain.')
        return
      }

      setCurrentStep(4) // Move to Step 4: Live
    } catch (err) {
      setApproveError(err.message || 'Failed to approve and start deployment.')
    } finally {
      setIsApproving(false)
    }
  }

  const handleLogout = async () => {
    try {
      await fetch('/auth/logout', { method: 'POST', credentials: 'include' })
    } catch {}
    setCurrentUser(null)
  }

  const handleNavSelect = (navId) => {
    setActiveNav(navId)
  }

  if (isLoginRoute) {
    return (
      <LoginScreen
        onNavigateHome={handleNavigateHome}
        onLoginSuccess={(user) => {
          setCurrentUser(user)
          handleNavigateHome()
        }}
      />
    )
  }

  return (
    <div className="app-layout">
      <Sidebar
        activeNav={activeNav}
        currentUser={currentUser}
        onNavSelect={handleNavSelect}
        onNavigateLogin={handleNavigateToLogin}
        onLogout={handleLogout}
      />

      <main className="app-main">
        <div className="app-content">
          {/* Header depending on active sidebar section */}
          {activeNav === 'new-deploy' && (
            <Header
              currentStep={currentStep}
              title={
                currentStep === 1
                  ? 'Deploy a new project'
                  : currentStep === 2
                  ? `Audit result: ${analysisResult?.project_name || 'Project'}`
                  : currentStep === 3
                  ? 'Review & approve fixes'
                  : `${analysisResult?.project_name || 'Project'} is deploying`
              }
              subtitle={
                currentStep === 1
                  ? 'Upload your FastAPI project ZIP to audit security, propose fixes, and deploy safely to Render.'
                  : currentStep === 2
                  ? `Run ID: ${analysisResult?.run_id || analysisResult?.id || 'pending'} • Deploy Readiness Score: ${analysisResult?.score ?? '--'}/100`
                  : currentStep === 3
                  ? 'Inspect proposed patches with unified diffs. Nothing is applied without your approval.'
                  : 'Track real-time deployment to Render and automated post-deploy health checks.'
              }
              onStepClick={(stepId) => {
                if (stepId === 1 || (stepId <= 4 && analysisResult)) {
                  setCurrentStep(stepId)
                }
              }}
            />
          )}

          {activeNav === 'history' && (
            <header className="page-header">
              <h2 className="page-title">Deployment History</h2>
              <p className="page-subtitle">Track all past audit scans, safety scores, and Render deployments.</p>
            </header>
          )}

          {activeNav === 'connections' && (
            <header className="page-header">
              <h2 className="page-title">Service Connections</h2>
              <p className="page-subtitle">Status of Google Gemini, GitHub, and Render integrations.</p>
            </header>
          )}

          {activeNav === 'settings' && (
            <header className="page-header">
              <h2 className="page-title">Settings & Policy</h2>
              <p className="page-subtitle">Configuration parameters, security sandbox limits, and scoring rules.</p>
            </header>
          )}

          {/* Section 1: New Deploy Flow */}
          {activeNav === 'new-deploy' && (
            <>
              {currentStep === 1 && (
                <UploadScreen onAnalyzeSuccess={handleAnalyzeSuccess} />
              )}

              {currentStep === 2 && (
                <AuditScreen
                  analysisResult={analysisResult}
                  repoConfig={repoConfig}
                  onProceedToFix={handleProceedToFix}
                  onUploadAnother={handleResetRun}
                />
              )}

              {currentStep === 3 && (
                <Card
                  title="Review & Approve Fixes"
                  subtitle="Inspect proposed patches before git commit and push."
                >
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                    {approveError && (
                      <div className="alert-banner alert-banner-danger" role="alert">
                        <strong>Error: </strong>
                        <span>{approveError}</span>
                      </div>
                    )}

                    <p style={{ color: 'var(--color-muted)', fontSize: '14px', lineHeight: 1.5 }}>
                      {analysisResult?.patches?.length > 0
                        ? `Saksham generated ${analysisResult.patches.length} patch proposal(s). Review diffs before proceeding to live deployment.`
                        : 'No patches needed. Ready to deploy directly to Render.'}
                    </p>

                    {analysisResult?.patches?.length > 0 && (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                        {analysisResult.patches.map((patch, idx) => (
                          <div
                            key={patch.id || `patch-${idx}`}
                            style={{
                              padding: '12px 16px',
                              backgroundColor: 'var(--color-surface-sunken)',
                              borderRadius: '8px',
                              border: '1px solid var(--color-border)',
                            }}
                          >
                            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                              <strong style={{ fontSize: '14px', color: 'var(--color-ink)' }}>{patch.file}</strong>
                              <span style={{ fontSize: '12px', color: 'var(--color-muted)' }}>{patch.reason}</span>
                            </div>
                            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', overflowX: 'auto', backgroundColor: 'var(--color-surface)', padding: '8px', borderRadius: '4px' }}>
                              <div style={{ color: 'var(--color-high-text)' }}>- {patch.old || '(empty)'}</div>
                              <div style={{ color: 'var(--color-success-text)' }}>+ {patch.new}</div>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}

                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '8px' }}>
                      <Button variant="secondary" onClick={() => setCurrentStep(2)} disabled={isApproving}>
                        Back to Audit
                      </Button>
                      <Button variant="primary" onClick={handleProceedToDeploy} disabled={isApproving}>
                        {isApproving ? 'Applying Patches...' : 'Approve and Deploy'}
                      </Button>
                    </div>
                  </div>
                </Card>
              )}

              {currentStep === 4 && (
                <LiveScreen
                  runId={analysisResult?.run_id || analysisResult?.id}
                  projectName={analysisResult?.project_name || 'Project'}
                  initialScore={analysisResult?.score}
                  repoConfig={repoConfig}
                  onDeployAnother={handleResetRun}
                />
              )}
            </>
          )}

          {/* Section 2: History Screen */}
          {activeNav === 'history' && (
            <HistoryScreen onNavigateToNewDeploy={() => handleResetRun()} />
          )}

          {/* Section 3: Connections Screen */}
          {activeNav === 'connections' && (
            <ConnectionsScreen />
          )}

          {/* Section 4: Settings Screen */}
          {activeNav === 'settings' && (
            <SettingsScreen />
          )}
        </div>
      </main>
    </div>
  )
}
