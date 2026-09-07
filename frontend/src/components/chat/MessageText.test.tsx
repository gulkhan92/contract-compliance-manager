import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { MessageText } from './MessageText'

const citation = {
  ref_number: 1,
  source_chunk_id: 'chunk-1',
  contract_id: 'contract-1',
  contract_title: 'Acme NDA',
  snippet: 'Either party may terminate upon 60 days notice.',
  is_reference_corpus: false,
}

describe('MessageText', () => {
  it('renders plain text with no citation markers unchanged', () => {
    render(<MessageText text="No citations here." citations={[]} onCitationClick={vi.fn()} />)

    expect(screen.getByText('No citations here.')).toBeInTheDocument()
  })

  it('renders a resolvable [n] marker as a clickable citation chip', () => {
    render(
      <MessageText
        text="The notice period is 60 days [1]."
        citations={[citation]}
        onCitationClick={vi.fn()}
      />,
    )

    expect(screen.getByRole('button', { name: /view source 1/i })).toBeInTheDocument()
  })

  it('calls onCitationClick with the matching citation when a chip is clicked', async () => {
    const onCitationClick = vi.fn()
    const user = userEvent.setup()
    render(
      <MessageText
        text="The notice period is 60 days [1]."
        citations={[citation]}
        onCitationClick={onCitationClick}
      />,
    )

    await user.click(screen.getByRole('button', { name: /view source 1/i }))

    expect(onCitationClick).toHaveBeenCalledWith(citation)
  })

  it('renders an unresolvable marker as plain text, not a dead button', () => {
    const { container } = render(
      <MessageText text="Something cited as [7]." citations={[citation]} onCitationClick={vi.fn()} />,
    )

    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    expect(container.textContent).toBe('Something cited as [7].')
  })

  it('renders multiple distinct citation chips', () => {
    const citation2 = { ...citation, ref_number: 2, contract_title: 'Rogers MSA' }
    render(
      <MessageText
        text="First point [1]. Second point [2]."
        citations={[citation, citation2]}
        onCitationClick={vi.fn()}
      />,
    )

    expect(screen.getByRole('button', { name: /view source 1/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /view source 2/i })).toBeInTheDocument()
  })
})
