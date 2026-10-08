import React, { useState } from 'react'
import Card from './Card'
import Button from './Button'
import Badge from './Badge'

/**
 * AuditScreen Component for Step 2 of the Saksham Pipeline.
 * Displays the Deploy Readiness Score, itemized deduction reasons,
 * categorized security & config issues with severity filtering,
 * and suggested patches summary.
 */
export default function AuditScreen({
  analysisResult,
  repoConfig,
  onProceedToFix,
  onUploadAnother,
}) {
  const [severityFilter, setSeverityFilter] = useState('all')

  if (!analysisResult) {
    return (
      <Card title="No Analysis Data" subtitle="Please upload and analyze a project archive first.">
        <div style={{ textAlign: 'center', padding: '32px 0' }}>
          <p style={{ color: 'var(--color-muted)', marginBottom: '16px' }}>
            No active analysis was found for this session.
          </p>
          <Button variant="primary" onClick={onUploadAnother}>
            Go to Upload
          </Button>
        </div>
      </Card>
    )
  }

  const {
    id: runId,
    project_name: projectName = 'Project',
    score = 100,
    reasons = [],
    issues = [],
    patches = [],
    framework = 'FastAPI',
    port,
    history_status: historyStatus,
  } = analysisResult

  // Severity Counts
  const highCount = issues.filter((i) => i.severity === 'high').length
  const medCount = issues.filter((i) => i.severity === 'medium').length
  const lowCount = issues.filter((i) => i.severity === 'low').length

  // Filtered Issues
  const filteredIssues = issues.filter((issue) => {
    if (severityFilter === 'all') return true
    return issue.severity === severityFilter
  })

  // Score Interpretation & Color Logic
  let scoreColor = 'var(--color-success-text)'
  let scoreStatusBadge = <Badge variant="success">Ready to Deploy</Badge>
  let scoreStatusText = 'No critical security risks found. Project meets pre-push standards.'

  if (highCount > 0 || score < 60) {
    scoreColor = 'var(--color-high-text)'
    scoreStatusBadge = <Badge variant="high">Not Safe to Push</Badge>
    scoreStatusText = `${highCount} critical security issue(s) detected. Push blocked until secrets are resolved.`
  } else if (medCount > 0 || score < 85) {
    scoreColor = 'var(--color-med-text)'
    scoreStatusBadge = <Badge variant="medium">Fixes Recommended</Badge>
    scoreStatusText = 'Configuration issues found. Automated fixes are available for review.'
  }

  const isClean = issues.length === 0 && score === 100

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--card-gap)' }}>
      {/* Top Banner Alert if high risks found */}
      {highCount > 0 && (
        <div className="alert-banner alert-banner-danger" role="alert">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ flexShrink: 0 }}>
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="8" x2="12" y2="12" />
            <line x1="12" y1="16" x2="12.01" y2="16" />
          </svg>
          <div>
            <strong>Secret Gate Active: </strong>
            <span>
              {highCount} secret leak(s) detected. Saksham blocks repository creation and deployment until high-severity secrets are masked or fixed.
            </span>
          </div>
        </div>
      )}

      {/* Deploy Readiness Score Card */}
      <Card title="Deploy Readiness Score" subtitle={`Project: ${projectName} • Framework: ${framework} ${port ? `• Port: ${port}` : ''}`}>
        <div className="score-card-layout">
          <div className="score-display-box">
            <span className="score-label">Readiness Score</span>
            <div className="score-number" style={{ color: scoreColor }}>
              {score}
              <span style={{ fontSize: '24px', color: 'var(--color-muted)', fontWeight: 600 }}>/100</span>
            </div>
            <div className="score-bar-track">
              <div
                className="score-bar-fill"
                style={{
                  width: `${Math.max(0, Math.min(100, score))}%`,
                  backgroundColor: scoreColor,
                }}
              />
            </div>
            <div style={{ marginTop: '8px' }}>{scoreStatusBadge}</div>
          </div>

          <div className="score-details-box">
            <h4 style={{ fontSize: '15px', fontWeight: 800, color: 'var(--color-ink)' }}>
              Score Breakdown & Deductions
            </h4>
            <p style={{ fontSize: '13px', color: 'var(--color-muted)' }}>
              {scoreStatusText} (Base 100: High issues -30, Medium -15, Low -5).
            </p>

            {reasons.length > 0 ? (
              <ul className="score-reasons-list">
                {reasons.map((reason, idx) => (
                  <li key={idx} className="score-reason-item">
                    <span className="score-reason-bullet">•</span>
                    <span>{reason}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <div style={{ fontSize: '13px', color: 'var(--color-success-text)', fontWeight: 600 }}>
                ✓ Perfect score: No deductions applied.
              </div>
            )}

            {historyStatus && (
              <div style={{ fontSize: '12px', color: 'var(--color-muted)', marginTop: '4px' }}>
                <strong>Git History: </strong>
                <span>{historyStatus}</span>
              </div>
            )}
          </div>
        </div>
      </Card>

      {/* Issues Breakdown Card */}
      <Card
        title={`Audit Findings (${issues.length})`}
        subtitle="Itemized security vulnerabilities and configuration anomalies detected in your project."
      >
        {isClean ? (
          <div style={{ textAlign: 'center', padding: '36px 20px' }}>
            <div
              style={{
                width: '48px',
                height: '48px',
                borderRadius: '50%',
                backgroundColor: 'var(--color-success-tint)',
                color: 'var(--color-success-text)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                margin: '0 auto 12px',
              }}
            >
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <polyline points="20 6 9 17 4 12" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
            <h4 style={{ fontSize: '16px', fontWeight: 800, color: 'var(--color-ink)', marginBottom: '6px' }}>
              Clean Project — No Issues Found
            </h4>
            <p style={{ fontSize: '14px', color: 'var(--color-muted)', maxWidth: '420px', margin: '0 auto' }}>
              Your project passes all security, secret leak, and deployment configuration static checks.
            </p>
          </div>
        ) : (
          <div>
            {/* Filter Pills */}
            <div className="issues-filter-bar">
              <button
                type="button"
                className={`filter-pill-btn ${severityFilter === 'all' ? 'active' : ''}`}
                onClick={() => setSeverityFilter('all')}
                aria-pressed={severityFilter === 'all'}
              >
                <span>All Issues</span>
                <span className="filter-count-badge">{issues.length}</span>
              </button>

              <button
                type="button"
                className={`filter-pill-btn ${severityFilter === 'high' ? 'active' : ''}`}
                onClick={() => setSeverityFilter('high')}
                aria-pressed={severityFilter === 'high'}
              >
                <span>High Severity</span>
                <span className="filter-count-badge">{highCount}</span>
              </button>

              <button
                type="button"
                className={`filter-pill-btn ${severityFilter === 'medium' ? 'active' : ''}`}
                onClick={() => setSeverityFilter('medium')}
                aria-pressed={severityFilter === 'medium'}
              >
                <span>Medium</span>
                <span className="filter-count-badge">{medCount}</span>
              </button>

              <button
                type="button"
                className={`filter-pill-btn ${severityFilter === 'low' ? 'active' : ''}`}
                onClick={() => setSeverityFilter('low')}
                aria-pressed={severityFilter === 'low'}
              >
                <span>Low</span>
                <span className="filter-count-badge">{lowCount}</span>
              </button>
            </div>

            {/* Filtered Issues List */}
            {filteredIssues.length === 0 ? (
              <p style={{ color: 'var(--color-muted)', padding: '16px 0', textAlign: 'center' }}>
                No issues match the selected severity filter.
              </p>
            ) : (
              <div className="issues-list">
                {filteredIssues.map((issue, idx) => (
                  <div key={issue.id || `issue-${idx}`} className="issue-row">
                    <div className="issue-row-header">
                      <div className="issue-title-group">
                        <Badge variant={issue.severity}>{issue.severity}</Badge>
                        <span className="issue-title">{issue.title}</span>
                      </div>
                      {issue.file_path && (
                        <span className="issue-location">
                          {issue.file_path}
                          {issue.line_number ? `:${issue.line_number}` : ''}
                        </span>
                      )}
                    </div>
                    <p className="issue-explanation">{issue.explanation}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </Card>

      {/* Suggested Fixes Summary Card */}
      <Card
        title="Suggested Fixes & Next Steps"
        subtitle="Saksham has prepared safe patch proposals for review."
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <p style={{ fontSize: '14px', color: 'var(--color-muted)', lineHeight: 1.5 }}>
            {patches.length > 0 ? (
              <>
                <strong>{patches.length} fix proposal(s)</strong> are available. In the next step, you can inspect unified diffs and approve fixes before any files are modified or pushed to GitHub.
              </>
            ) : (
              'No automated patch proposals were required for this audit.'
            )}
          </p>

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px' }}>
            <Button variant="secondary" onClick={onUploadAnother}>
              Upload another project
            </Button>
            <Button variant="primary" onClick={onProceedToFix}>
              {patches.length > 0 ? `Proceed to Review ${patches.length} Fixes` : 'Proceed to Deploy'}
            </Button>
          </div>
        </div>
      </Card>
    </div>
  )
}
