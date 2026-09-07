import type { components } from './api-schema'

type ContractStatus = components['schemas']['ContractStatus']
type ObligationStatus = components['schemas']['ObligationStatus']
type AlertStatus = components['schemas']['AlertStatus']
type ExtractionJobStatus = components['schemas']['ExtractionJobStatus']
type ChatConfidence = components['schemas']['ChatConfidence']
type ChatIntent = components['schemas']['ChatIntent']
type DeclineReason = Exclude<
  components['schemas']['AnswerDiagnostics']['decision_reason'],
  'answered'
>

export type BadgeTone = 'neutral' | 'info' | 'warning' | 'danger' | 'success'

export const CONTRACT_STATUS_LABEL: Record<ContractStatus, string> = {
  processing: 'Processing',
  needs_review: 'Needs Review',
  active: 'Active',
  expired: 'Expired',
  terminated: 'Terminated',
  error: 'Error',
}

export const CONTRACT_STATUS_TONE: Record<ContractStatus, BadgeTone> = {
  processing: 'info',
  needs_review: 'warning',
  active: 'success',
  expired: 'neutral',
  terminated: 'neutral',
  error: 'danger',
}

export const OBLIGATION_STATUS_LABEL: Record<ObligationStatus, string> = {
  upcoming: 'Upcoming',
  at_risk: 'At Risk',
  overdue: 'Overdue',
  resolved: 'Resolved',
  waived: 'Waived',
}

export const OBLIGATION_STATUS_TONE: Record<ObligationStatus, BadgeTone> = {
  upcoming: 'info',
  at_risk: 'warning',
  overdue: 'danger',
  resolved: 'success',
  waived: 'neutral',
}

export const ALERT_STATUS_LABEL: Record<AlertStatus, string> = {
  pending: 'Pending',
  sent: 'Sent',
  failed: 'Failed',
  cancelled: 'Dismissed',
}

export const ALERT_STATUS_TONE: Record<AlertStatus, BadgeTone> = {
  pending: 'info',
  sent: 'success',
  failed: 'danger',
  cancelled: 'neutral',
}

export const EXTRACTION_JOB_STATUS_LABEL: Record<ExtractionJobStatus, string> = {
  queued: 'Queued',
  running: 'Running',
  succeeded: 'Succeeded',
  failed: 'Failed',
}

export const EXTRACTION_JOB_STATUS_TONE: Record<ExtractionJobStatus, BadgeTone> = {
  queued: 'neutral',
  running: 'info',
  succeeded: 'success',
  failed: 'danger',
}

export const CHAT_CONFIDENCE_LABEL: Record<ChatConfidence, string> = {
  high: 'High confidence',
  medium: 'Medium confidence',
  low: 'Low confidence',
  insufficient_information: 'Not enough information',
}

export const CHAT_CONFIDENCE_TONE: Record<ChatConfidence, BadgeTone> = {
  high: 'success',
  medium: 'info',
  low: 'warning',
  insufficient_information: 'neutral',
}

export const CHAT_INTENT_LABEL: Record<ChatIntent, string> = {
  domain_question: 'Contract Q&A',
  clause_benchmark: 'Clause benchmark',
  calendar_query: 'Compliance calendar',
  out_of_scope: 'Out of scope',
}

/**
 * Backend's AnswerDiagnostics.decision_reason (pipeline.py's retrieval
 * outcome plus generation.py's own guardrail chain), collapsed to one
 * plain-language line each for the "why not enough information?" panel.
 */
export const DECLINE_REASON_LABEL: Record<DeclineReason, string> = {
  no_candidates_found: "Nothing in your organization's contracts matched this question",
  below_relevance_threshold: "The closest matches found weren't relevant enough to trust",
  llm_unavailable: 'The AI model was temporarily unavailable',
  llm_self_declined: "The model reviewed what was found and didn't consider it enough",
  legal_advice_framing: 'The draft answer read as legal advice rather than contract information',
  uncited_claim: 'The draft answer made a claim that no source passage actually supported',
  failed_faithfulness_check: "The draft answer didn't hold up against the source text on review",
}

export function categoryLabel(category: string): string {
  return category
    .toLowerCase()
    .split('_')
    .map((word) => word[0].toUpperCase() + word.slice(1))
    .join(' ')
}
