import { useState } from 'react'
import { ChevronDown, ChevronUp, SearchX } from 'lucide-react'

import { cn } from '@/lib/utils'
import { DECLINE_REASON_LABEL } from '@/lib/status'
import type { components } from '@/lib/api-schema'

type AnswerDiagnostics = components['schemas']['AnswerDiagnostics']
type RetrievalAttempt = components['schemas']['RetrievalAttempt']

function attemptLabel(attempt: RetrievalAttempt): string {
  if (attempt.scope === 'unrestricted') return 'Searched your entire organization'
  const count = attempt.narrowed_to_contract_count
  return `Searched ${count} contract${count === 1 ? '' : 's'} matching a name in your question`
}

function ScoreBadge({ passed, score }: { passed: boolean; score: number }) {
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center rounded-full px-1.5 py-0.5 text-[10px] font-semibold tabular-nums',
        passed
          ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
          : 'bg-muted text-muted-foreground',
      )}
    >
      {Math.round(score * 100)}% match
    </span>
  )
}

/**
 * The "why not enough information?" disclosure for a declined answer —
 * shown collapsed by default so it doesn't compete with the apology text,
 * but always available: a user weighing whether to trust a decline should
 * be able to see what was actually retrieved and at what confidence,
 * rather than take the fixed apology sentence on faith.
 */
export function RetrievalDiagnosticsPanel({ diagnostics }: { diagnostics: AnswerDiagnostics }) {
  const [open, setOpen] = useState(false)
  const reason =
    diagnostics.decision_reason === 'answered'
      ? null
      : DECLINE_REASON_LABEL[diagnostics.decision_reason]

  return (
    <div className="w-full border-t pt-2">
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        className="flex w-full items-center gap-1.5 text-left text-xs text-muted-foreground hover:text-foreground"
      >
        <SearchX className="size-3.5 shrink-0" />
        <span className="flex-1">Why not enough information?</span>
        {open ? <ChevronUp className="size-3.5 shrink-0" /> : <ChevronDown className="size-3.5 shrink-0" />}
      </button>
      {open ? (
        <div className="mt-2 flex flex-col gap-3">
          {reason ? <p className="text-xs text-muted-foreground">{reason}</p> : null}
          {diagnostics.attempts.map((attempt, attemptIndex) => (
            <div key={attemptIndex} className="flex flex-col gap-1.5">
              <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground/80">
                {attemptLabel(attempt)}
              </p>
              {attempt.top_candidates.length === 0 ? (
                <p className="rounded-md border border-dashed bg-muted/30 p-2.5 text-xs text-muted-foreground">
                  No passages were found at all — this contract may not have any indexed content.
                </p>
              ) : (
                <ul className="flex flex-col gap-1.5">
                  {attempt.top_candidates.map((candidate, candidateIndex) => (
                    <li
                      key={candidateIndex}
                      className="rounded-md border bg-muted/40 p-2.5 text-xs text-muted-foreground"
                    >
                      <div className="mb-1 flex items-center justify-between gap-2">
                        <span className="truncate font-medium text-foreground/80">
                          {candidate.contract_title}
                        </span>
                        <ScoreBadge passed={candidate.passed_threshold} score={candidate.score} />
                      </div>
                      <p className="line-clamp-2">{candidate.snippet}</p>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  )
}
