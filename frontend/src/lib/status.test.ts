import { describe, expect, it } from 'vitest'

import { categoryLabel } from './status'

describe('categoryLabel', () => {
  it('converts an ObligationCategory enum value into a readable label', () => {
    expect(categoryLabel('TERMINATION_NOTICE')).toBe('Termination Notice')
    expect(categoryLabel('RENEWAL')).toBe('Renewal')
    expect(categoryLabel('OTHER_OBLIGATION')).toBe('Other Obligation')
  })
})
