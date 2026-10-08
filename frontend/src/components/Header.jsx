import React from 'react'
import StepBar from './StepBar'

/**
 * Top Page Header containing the 4-step progress bar, page title, and subtitle.
 */
export default function Header({
  currentStep = 1,
  title = 'Deploy a new project',
  subtitle = 'Upload your FastAPI project ZIP to audit security, propose fixes, and deploy safely to Render.',
  onStepClick,
}) {
  return (
    <header className="page-header">
      <StepBar currentStep={currentStep} onStepClick={onStepClick} />
      <div>
        <h2 className="page-title">{title}</h2>
        {subtitle && <p className="page-subtitle">{subtitle}</p>}
      </div>
    </header>
  )
}
