import type { components } from '@/lib/api-schema'

type ChatCitation = components['schemas']['ChatCitation']

const CITATION_MARKER_PATTERN = /(\[\d+\])/g
const CITATION_NUMBER_PATTERN = /^\[(\d+)\]$/

/**
 * Renders inline `[n]` markers as clickable citation chips (plan §5) —
 * a first-class UI element, not a footnote. A marker with no matching
 * citation (shouldn't happen, given generation.py never leaves an
 * unresolved marker in a validated answer, but text is text) just
 * renders as plain characters rather than a dead button.
 */
export function MessageText({
  text,
  citations,
  onCitationClick,
}: {
  text: string
  citations: ChatCitation[]
  onCitationClick: (citation: ChatCitation) => void
}) {
  const citationsByRef = new Map(citations.map((c) => [c.ref_number, c]))
  const parts = text.split(CITATION_MARKER_PATTERN)

  return (
    <p className="whitespace-pre-wrap text-sm leading-relaxed">
      {parts.map((part, index) => {
        const match = CITATION_NUMBER_PATTERN.exec(part)
        const citation = match ? citationsByRef.get(Number(match[1])) : undefined
        if (match && citation) {
          return (
            <button
              key={index}
              type="button"
              onClick={() => onCitationClick(citation)}
              className="mx-0.5 inline-flex size-4 -translate-y-0.5 items-center justify-center rounded-full bg-primary/15 text-[10px] font-semibold text-primary align-super hover:bg-primary/25"
              aria-label={`View source ${match[1]}: ${citation.contract_title}`}
            >
              {match[1]}
            </button>
          )
        }
        return <span key={index}>{part}</span>
      })}
    </p>
  )
}
