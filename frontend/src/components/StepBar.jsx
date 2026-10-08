import React from 'react'

const STEPS = [
  { id: 1, key: 'upload', label: 'Upload' },
  { id: 2, key: 'audit', label: 'Audit' },
  { id: 3, key: 'fix', label: 'Fix' },
  { id: 4, key: 'deploy', label: 'Deploy' },
]

/**
 * 4-Step navigation/progress indicator as defined in DESIGN.md section 8.
 */
export default function StepBar({ currentStep = 1, onStepClick }) {
  return (
    <nav className="step-bar" aria-label="Deployment Progress">
      {STEPS.map((step) => {
        let statusClass = 'upcoming'
        if (step.id === currentStep) {
          statusClass = 'active'
        } else if (step.id < currentStep) {
          statusClass = 'completed'
        }

        return (
          <div
            key={step.key}
            className={`step-pill ${statusClass}`}
            role="status"
            aria-current={step.id === currentStep ? 'step' : undefined}
            onClick={() => onStepClick && onStepClick(step.id)}
            style={{ cursor: onStepClick ? 'pointer' : 'default' }}
          >
            <span className="step-number">{step.id}</span>
            <span>{step.label}</span>
          </div>
        )
      })}
    </nav>
  )
}
