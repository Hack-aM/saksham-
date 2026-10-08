import React, { useState, useRef } from 'react'
import Card from './Card'
import Button from './Button'
import Badge from './Badge'

const MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024 // 25 MB

function formatBytes(bytes) {
  if (bytes === 0) return '0 Bytes'
  const k = 1024
  const sizes = ['Bytes', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`
}

/**
 * UploadScreen Component for Step 1 of the Saksham Pipeline.
 * Handles drag-and-drop file upload, file validation, repo configuration,
 * and calling the POST /analyze backend endpoint.
 */
export default function UploadScreen({ onAnalyzeSuccess }) {
  const [file, setFile] = useState(null)
  const [repoName, setRepoName] = useState('')
  const [visibility, setVisibility] = useState('private')
  const [deployOn, setDeployOn] = useState('render')
  const [isDragActive, setIsDragActive] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [errorMessage, setErrorMessage] = useState('')

  const fileInputRef = useRef(null)

  const handleFileSelect = (selectedFile) => {
    setErrorMessage('')
    if (!selectedFile) return

    // 1. Validation: file extension must be .zip
    if (!selectedFile.name.toLowerCase().endsWith('.zip')) {
      setErrorMessage('Please select a valid .zip archive of your project.')
      return
    }

    // 2. Validation: file size must be within 25MB limit
    if (selectedFile.size > MAX_FILE_SIZE_BYTES) {
      setErrorMessage(
        `File size (${formatBytes(selectedFile.size)}) exceeds the maximum allowed limit of 25 MB.`
      )
      return
    }

    setFile(selectedFile)
    // Derive default repo name from file stem
    const defaultName = selectedFile.name
      .replace(/\.zip$/i, '')
      .replace(/[^a-zA-Z0-9._-]/g, '-')
      .toLowerCase()
    setRepoName(defaultName || 'my-fastapi-app')
  }

  const handleDrop = (e) => {
    e.preventDefault()
    setIsDragActive(false)
    if (isLoading) return

    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFileSelect(e.dataTransfer.files[0])
    }
  }

  const handleDragOver = (e) => {
    e.preventDefault()
    if (!isLoading) {
      setIsDragActive(true)
    }
  }

  const handleDragLeave = (e) => {
    e.preventDefault()
    setIsDragActive(false)
  }

  const handleClearFile = () => {
    if (isLoading) return
    setFile(null)
    setRepoName('')
    setErrorMessage('')
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  const handleAnalyze = async (e) => {
    e.preventDefault()
    setErrorMessage('')

    if (!file) {
      setErrorMessage('Please select a project ZIP file before analyzing.')
      return
    }

    if (!repoName.trim()) {
      setErrorMessage('Please provide a valid repository name.')
      return
    }

    setIsLoading(true)

    try {
      const formData = new FormData()
      formData.append('file', file)

      // Send to backend /analyze endpoint
      const response = await fetch('/analyze', {
        method: 'POST',
        body: formData,
      })

      if (!response.ok) {
        let errDetail = `Server returned status ${response.status}`
        try {
          const errData = await response.json()
          if (errData.detail) {
            errDetail = typeof errData.detail === 'string' ? errData.detail : JSON.stringify(errData.detail)
          }
        } catch {
          // fallback to status text
          errDetail = response.statusText || errDetail
        }
        throw new Error(errDetail)
      }

      const analysisData = await response.json()

      // Notify parent app of successful analysis
      if (onAnalyzeSuccess) {
        onAnalyzeSuccess(analysisData, {
          repoName: repoName.trim(),
          visibility,
          deployOn,
          fileName: file.name,
          fileSizeBytes: file.size,
        })
      }
    } catch (err) {
      setErrorMessage(
        err.message || 'An error occurred while analyzing the project. Please ensure the backend is running.'
      )
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--card-gap)' }}>
      {/* Error / Alert Banner */}
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

      {/* Upload Drop Zone Card */}
      <Card
        variant="dashed"
        className={isDragActive ? 'drag-active' : ''}
        style={{
          padding: '36px 20px',
          textAlign: 'center',
          cursor: isLoading ? 'not-allowed' : 'pointer',
        }}
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onClick={() => !file && !isLoading && fileInputRef.current?.click()}
        tabIndex={0}
        role="button"
        aria-label="Upload project ZIP file"
        onKeyDown={(e) => {
          if ((e.key === 'Enter' || e.key === ' ') && !file && !isLoading) {
            e.preventDefault()
            fileInputRef.current?.click()
          }
        }}
      >
        <input
          type="file"
          ref={fileInputRef}
          accept=".zip"
          style={{ display: 'none' }}
          id="project-zip-input"
          onChange={(e) => e.target.files && handleFileSelect(e.target.files[0])}
          disabled={isLoading}
        />

        {!file ? (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '12px', maxWidth: '480px', margin: '0 auto' }}>
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
              }}
            >
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" strokeLinecap="round" strokeLinejoin="round" />
                <polyline points="17 8 12 3 7 8" strokeLinecap="round" strokeLinejoin="round" />
                <line x1="12" y1="3" x2="12" y2="15" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
            <h3 style={{ fontSize: '17px', fontWeight: 800, color: 'var(--color-ink)' }}>
              Drag and drop your project ZIP here
            </h3>
            <p style={{ fontSize: '14px', color: 'var(--color-muted)' }}>
              Supports FastAPI projects up to 25 MB. All scans run in an isolated workspace without executing untrusted code.
            </p>
            <div style={{ marginTop: '4px' }}>
              <Button
                variant="secondary"
                disabled={isLoading}
                onClick={(e) => {
                  e.stopPropagation()
                  fileInputRef.current?.click()
                }}
              >
                Browse file
              </Button>
            </div>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', maxWidth: '540px', margin: '0 auto' }} onClick={(e) => e.stopPropagation()}>
            <div className="selected-file-box">
              <div className="selected-file-details">
                <div className="file-icon">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                    <polyline points="14 2 14 8 20 8" />
                    <line x1="16" y1="13" x2="8" y2="13" />
                    <line x1="16" y1="17" x2="8" y2="17" />
                    <polyline points="10 9 9 9 8 9" />
                  </svg>
                </div>
                <div className="file-meta">
                  <span className="file-name">{file.name}</span>
                  <span className="file-size">{formatBytes(file.size)}</span>
                </div>
              </div>
              <Button
                variant="secondary"
                disabled={isLoading}
                onClick={handleClearFile}
                style={{ minHeight: '36px', padding: '0 12px', fontSize: '13px' }}
              >
                Change
              </Button>
            </div>
          </div>
        )}
      </Card>

      {/* Deployment & Repository Configuration Form */}
      <Card title="Repository & Deployment Options" subtitle="Configure the target repository and hosting settings for this run.">
        <form onSubmit={handleAnalyze} style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          <div className="form-row">
            <div className="form-group">
              <label htmlFor="repo-name" className="form-label">
                Repository Name
              </label>
              <input
                id="repo-name"
                type="text"
                className="form-input"
                placeholder="e.g. my-fastapi-service"
                value={repoName}
                onChange={(e) => setRepoName(e.target.value)}
                disabled={isLoading}
                required
              />
            </div>

            <div className="form-group">
              <label htmlFor="repo-visibility" className="form-label">
                Visibility
              </label>
              <select
                id="repo-visibility"
                className="form-select"
                value={visibility}
                onChange={(e) => setVisibility(e.target.value)}
                disabled={isLoading}
              >
                <option value="private">Private (Recommended)</option>
                <option value="public">Public</option>
              </select>
            </div>

            <div className="form-group">
              <label htmlFor="deploy-target" className="form-label">
                Deploy On
              </label>
              <select
                id="deploy-target"
                className="form-select"
                value={deployOn}
                onChange={(e) => setDeployOn(e.target.value)}
                disabled={true}
              >
                <option value="render">Render (Standard)</option>
              </select>
            </div>
          </div>

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px', alignItems: 'center' }}>
            <Button
              type="submit"
              variant="primary"
              disabled={!file || isLoading}
              style={{ minWidth: '180px' }}
            >
              {isLoading ? (
                <>
                  <span className="spinner" aria-hidden="true"></span>
                  <span>Analyzing project...</span>
                </>
              ) : (
                'Analyze project'
              )}
            </Button>
          </div>
        </form>
      </Card>

      {/* Saksham Safety Guarantees / Process Overview */}
      <div className="overview-grid">
        <div className="pipeline-feature-card">
          <div className="feature-icon-wrapper">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <h4 className="feature-title">Pre-Push Audit</h4>
            <Badge variant="high">Secret Gate</Badge>
          </div>
          <p className="feature-text">
            Static scan of files, git history, and configuration checks. Blocks pushes if any secret is exposed.
          </p>
        </div>

        <div className="pipeline-feature-card">
          <div className="feature-icon-wrapper">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="16 18 22 12 16 6" strokeLinecap="round" strokeLinejoin="round" />
              <polyline points="8 6 2 12 8 18" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <h4 className="feature-title">Safe Auto-Fix</h4>
            <Badge variant="info">Diff Review</Badge>
          </div>
          <p className="feature-text">
            Generates starter templates and LLM patch proposals with unified diffs. Requires explicit human approval.
          </p>
        </div>

        <div className="pipeline-feature-card">
          <div className="feature-icon-wrapper">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.87a3.37 3.37 0 0 0-.94-2.61c3.14-.35 6.44-1.54 6.44-7A5.44 5.44 0 0 0 20 4.77 5.07 5.07 0 0 0 19.91 1S18.73.65 16 2.48a13.38 13.38 0 0 0-7 0C6.27.65 5.09 1 5.09 1A5.07 5.07 0 0 0 5 4.77a5.44 5.44 0 0 0-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 0 0 9 18.13V22" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <h4 className="feature-title">Push to GitHub</h4>
            <Badge variant="medium">New Repo Only</Badge>
          </div>
          <p className="feature-text">
            Creates a new clean repository. Never deletes, overwrites, or force-pushes to existing repositories.
          </p>
        </div>

        <div className="pipeline-feature-card">
          <div className="feature-icon-wrapper">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <h4 className="feature-title">Deploy & Verify</h4>
            <Badge variant="success">Auto Self-Fix</Badge>
          </div>
          <p className="feature-text">
            Deploys to Render, verifies live endpoint health, and automatically repairs deployment failures up to 3 attempts.
          </p>
        </div>
      </div>
    </div>
  )
}
