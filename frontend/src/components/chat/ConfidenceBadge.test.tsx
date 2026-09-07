import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { ConfidenceBadge } from './ConfidenceBadge'

describe('ConfidenceBadge', () => {
  it('renders the label for a normal confidence level', () => {
    render(<ConfidenceBadge confidence="high" />)

    expect(screen.getByText('High confidence')).toBeInTheDocument()
  })

  it('renders insufficient_information distinctly from a normal confidence badge', () => {
    const { container } = render(<ConfidenceBadge confidence="insufficient_information" />)

    expect(screen.getByText('Not enough information')).toBeInTheDocument()
    // Styled with a dashed border rather than the filled StatusBadge look,
    // so it can never be mistaken for a confident answer at a glance.
    expect(container.querySelector('.border-dashed')).toBeInTheDocument()
  })

  it.each(['medium', 'low'] as const)('renders a label for %s confidence', (confidence) => {
    render(<ConfidenceBadge confidence={confidence} />)

    expect(screen.getByText(`${confidence[0].toUpperCase()}${confidence.slice(1)} confidence`))
      .toBeInTheDocument()
  })
})
