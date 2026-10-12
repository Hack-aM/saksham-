import React, { useState } from 'react'
import Button from './Button'

/**
 * T36: Authenticated Login & Registration Screen.
 * Scoped dark-theme layout with two columns:
 * - Left: centered form column (max-width 400px)
 * - Right: sample product preview panel (hidden on <= 860px)
 *
 * Supports:
 * - GitHub OAuth sign-in flow
 * - Email/password authentication and registration
 * - Client feedback and session establishment
 */
export default function LoginScreen({ onNavigateHome, onLoginSuccess }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [isCreateAccount, setIsCreateAccount] = useState(false)
  const [errorMessage, setErrorMessage] = useState('')
  const [infoNotice, setInfoNotice] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)

  const handleGitHubSignIn = async (e) => {
    e.preventDefault()
    setErrorMessage('')
    setInfoNotice('')
    try {
      const resp = await fetch('/auth/github', {
        headers: { Accept: 'application/json' },
      })
      if (!resp.ok) {
        let errText = 'GitHub OAuth is not configured on this server. Please sign in with email.'
        try {
          const errData = await resp.json()
          if (errData.detail) errText = errData.detail
        } catch {}
        setErrorMessage(errText)
        return
      }
      const data = await resp.json().catch(() => ({}))
      if (data.auth_url) {
        window.location.href = data.auth_url
      } else {
        window.location.href = '/auth/github'
      }
    } catch {
      window.location.href = '/auth/github'
    }
  }

  const handleEmailSubmit = async (e) => {
    e.preventDefault()
    setErrorMessage('')
    setInfoNotice('')

    if (!email || !password) {
      setErrorMessage('Please provide both email and password.')
      return
    }

    if (isCreateAccount && password.length < 8) {
      setErrorMessage('Password must be at least 8 characters long.')
      return
    }

    setIsSubmitting(true)
    try {
      const endpoint = isCreateAccount ? '/auth/register' : '/auth/login'
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ email, password }),
      })

      const data = await response.json().catch(() => ({}))

      if (!response.ok) {
        let msg = data.detail || (isCreateAccount ? 'Registration failed.' : 'Sign in failed.')
        if (Array.isArray(msg)) {
          msg = msg.map((m) => m.msg || JSON.stringify(m)).join(', ')
        }
        throw new Error(msg)
      }

      if (onLoginSuccess) {
        onLoginSuccess(data.user)
      }
      if (onNavigateHome) {
        onNavigateHome()
      }
    } catch (err) {
      setErrorMessage(err.message || 'Authentication failed. Please check your credentials.')
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleForgotPassword = (e) => {
    e.preventDefault()
    setErrorMessage('')
    setInfoNotice('Password reset: Contact your workspace administrator to reset credentials.')
  }

  const toggleMode = (e) => {
    e.preventDefault()
    setIsCreateAccount(!isCreateAccount)
    setErrorMessage('')
    setInfoNotice('')
  }

  return (
    <div className="login-page">
      {/* Left Column: Form Column (max-width 400px, vertically centered) */}
      <section className="login-form-col" aria-label={isCreateAccount ? 'Create account form' : 'Sign in form'}>
        <div className="login-form-container">
          {/* 1. Logo "Saksham" (accent #4FC4BB, 22px / weight 800) */}
          <div className="login-logo-wrapper">
            <a
              href="/"
              className="login-logo"
              onClick={(e) => {
                if (onNavigateHome) {
                  e.preventDefault()
                  onNavigateHome()
                }
              }}
              title="Saksham - Return to application"
            >
              Saksham
            </a>
          </div>

          {/* 2. H1 */}
          <h1 className="login-heading">
            {isCreateAccount ? 'Create your Saksham account' : 'Sign in to Saksham'}
          </h1>

          {/* 3. Subtitle */}
          <p className="login-subtitle">
            {isCreateAccount
              ? 'Get started with pre-push audit and deployment safety.'
              : 'Audit your project before it reaches GitHub. Deploy with confidence.'}
          </p>

          {/* Error notice */}
          {errorMessage && (
            <div className="login-alert-notice" role="alert" aria-live="assertive" style={{ borderLeftColor: 'var(--login-high-badge-text)' }}>
              <span className="login-alert-icon" aria-hidden="true" style={{ color: 'var(--login-high-badge-text)' }}>⚠</span>
              <span>{errorMessage}</span>
            </div>
          )}

          {/* Info notice */}
          {infoNotice && (
            <div className="login-alert-notice" role="status" aria-live="polite">
              <span className="login-alert-icon" aria-hidden="true">ℹ</span>
              <span>{infoNotice}</span>
            </div>
          )}

          {/* 4. Primary button "Continue with GitHub" with GitHub mark icon */}
          <Button
            className="login-btn-github"
            onClick={handleGitHubSignIn}
            aria-label="Continue with GitHub"
            disabled={isSubmitting}
          >
            <svg
              className="login-github-icon"
              viewBox="0 0 24 24"
              width="20"
              height="20"
              fill="currentColor"
              aria-hidden="true"
            >
              <path
                fillRule="evenodd"
                clipRule="evenodd"
                d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.53 1.032 1.53 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z"
              />
            </svg>
            <span>Continue with GitHub</span>
          </Button>

          {/* 5. Helper text */}
          <p className="login-helper-text">
            Saksham only creates new repositories. It never deletes or force-pushes.
          </p>

          {/* 6. Divider */}
          <div className="login-divider" role="separator" aria-label={isCreateAccount ? 'or register with email' : 'or sign in with email'}>
            <span className="login-divider-line" aria-hidden="true" />
            <span className="login-divider-text">
              {isCreateAccount ? 'or register with email' : 'or sign in with email'}
            </span>
            <span className="login-divider-line" aria-hidden="true" />
          </div>

          {/* Email + Password Form */}
          <form className="login-form" onSubmit={handleEmailSubmit} noValidate>
            {/* 7. Email input */}
            <div className="login-form-group">
              <label htmlFor="login-email-input" className="login-label">
                Email
              </label>
              <input
                id="login-email-input"
                name="email"
                type="email"
                autoComplete="email"
                className="login-input"
                placeholder="you@college.edu"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                disabled={isSubmitting}
              />
            </div>

            {/* 8. Password input */}
            <div className="login-form-group">
              <label htmlFor="login-password-input" className="login-label">
                Password
              </label>
              <input
                id="login-password-input"
                name="password"
                type="password"
                autoComplete={isCreateAccount ? 'new-password' : 'current-password'}
                className="login-input"
                placeholder={isCreateAccount ? 'Create a secure password (min 8 chars)' : 'Enter your password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                disabled={isSubmitting}
              />
            </div>

            {/* 9. "Forgot password?" link right-aligned (only on sign in mode) */}
            {!isCreateAccount && (
              <div className="login-forgot-wrapper">
                <a
                  href="#forgot"
                  className="login-link login-forgot-link"
                  onClick={handleForgotPassword}
                >
                  Forgot password?
                </a>
              </div>
            )}

            {/* 10. Secondary button */}
            <Button
              type="submit"
              variant="secondary"
              className="login-btn-email"
              disabled={isSubmitting}
            >
              {isSubmitting
                ? 'Processing...'
                : isCreateAccount
                ? 'Create account'
                : 'Sign in with email'}
            </Button>
          </form>

          {/* 11. Footer toggle */}
          <footer className="login-footer">
            <span>{isCreateAccount ? 'Already have an account? ' : 'New to Saksham? '}</span>
            <a
              href="#toggle-mode"
              className="login-link login-create-link"
              onClick={toggleMode}
            >
              {isCreateAccount ? 'Sign in' : 'Create an account'}
            </a>
          </footer>
        </div>
      </section>

      {/* Right Column: Product preview panel (hidden below 860px) */}
      <aside className="login-preview-col" aria-label="Product preview">
        <div className="login-preview-container">
          <div className="login-preview-label">What you get on every run</div>

          {/* Main sample run card */}
          <div className="login-card login-main-preview-card">
            <div className="login-preview-card-header">
              <div className="login-readiness-wrapper">
                <span className="login-readiness-label">Deploy readiness</span>
                <div className="login-score-row">
                  <span className="login-score-number">40</span>
                  <span className="login-score-total">/100</span>
                </div>
              </div>
              <div className="login-badge-push-blocked" aria-label="Push blocked status">
                Push blocked
              </div>
            </div>

            <div className="login-preview-rows" role="list">
              <div className="login-preview-row" role="listitem">
                <span className="login-badge login-badge-high">High</span>
                <span className="login-preview-row-text">
                  API key found in config.py, line 12
                </span>
              </div>

              <div className="login-preview-row" role="listitem">
                <span className="login-badge login-badge-med">Medium</span>
                <span className="login-preview-row-text">
                  .env is not in .gitignore
                </span>
              </div>

              <div className="login-preview-row" role="listitem">
                <span className="login-badge login-badge-med">Medium</span>
                <span className="login-preview-row-text">
                  Port is hardcoded
                </span>
              </div>
            </div>
          </div>

          {/* Sub cards: Fixes and Deploy */}
          <div className="login-subcards-grid">
            <div className="login-card login-subcard">
              <span className="login-subcard-label">Fixes</span>
              <p className="login-subcard-title">You approve each diff</p>
            </div>

            <div className="login-card login-subcard">
              <span className="login-subcard-label">Deploy</span>
              <p className="login-subcard-title">Live URL, health checked</p>
            </div>
          </div>
        </div>
      </aside>
    </div>
  )
}
