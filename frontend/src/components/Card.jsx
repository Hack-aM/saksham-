import React from 'react'

/**
 * Reusable surface card container following DESIGN.md specifications.
 */
export default function Card({
  children,
  title,
  subtitle,
  headerAction,
  variant = 'default',
  className = '',
  style = {},
  ...props
}) {
  const cardClass = [
    'card',
    variant === 'dashed' ? 'card-dashed' : '',
    className,
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <div className={cardClass} style={style} {...props}>
      {(title || subtitle || headerAction) && (
        <div className="card-header">
          <div>
            {title && <h3 className="card-title">{title}</h3>}
            {subtitle && <p className="card-description">{subtitle}</p>}
          </div>
          {headerAction && <div className="card-header-action">{headerAction}</div>}
        </div>
      )}
      {children}
    </div>
  )
}
