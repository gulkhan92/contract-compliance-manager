import { StatusBadge } from '@/components/StatusBadge'
import { CHAT_CONFIDENCE_LABEL, CHAT_CONFIDENCE_TONE } from '@/lib/status'
import type { components } from '@/lib/api-schema'

type ChatConfidence = components['schemas']['ChatConfidence']

/**
 * insufficient_information gets its own distinct treatment (dashed
 * border, no fill) rather than just reusing the neutral StatusBadge tone
 * — per the plan, a hedge must never be visually mistaken for a normal,
 * confident answer.
 */
export function ConfidenceBadge({ confidence }: { confidence: ChatConfidence }) {
  if (confidence === 'insufficient_information') {
    return (
      <span className="inline-flex items-center rounded-full border border-dashed border-muted-foreground/40 px-2 py-0.5 text-xs font-medium text-muted-foreground">
        {CHAT_CONFIDENCE_LABEL[confidence]}
      </span>
    )
  }
  return <StatusBadge tone={CHAT_CONFIDENCE_TONE[confidence]} label={CHAT_CONFIDENCE_LABEL[confidence]} />
}
