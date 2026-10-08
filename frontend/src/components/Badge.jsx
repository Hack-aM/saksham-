import React from 'react'

/**
 * Reusable severity and status badge matching DESIGN.md color rules.
 */
export default function Badge({
  children,
  variant = 'neutral',
  className = '',
  style = {},
  ...props
}) {
  const badgeClass = [
    'badge',
    variant === 'high' ? 'badge-high' : '',
    variant === 'medium' ? 'badge-medium' : '',
    variant === 'low' ? 'badge-low' : '',
    variant === 'info' ? 'badge-info' : '',
    variant === 'success' ? 'badge-success' : '',
    variant === 'neutral' ? 'badge-neutral' : '',
    className,
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <span className={badgeClass} style={style} {...props}>
      {children}
    </span>
  )
}
