import { apiOrigin, getAccessToken } from '@/lib/api-client'
import type { components } from '@/lib/api-schema'

type ChatCitation = components['schemas']['ChatCitation']
type ChatConfidence = components['schemas']['ChatConfidence']
type ChatIntent = components['schemas']['ChatIntent']
type AnswerDiagnostics = components['schemas']['AnswerDiagnostics']

export interface ChatStreamDone {
  type: 'done'
  message_id: string
  citations: ChatCitation[]
  confidence: ChatConfidence
  intent: ChatIntent
  retrieval_diagnostics: AnswerDiagnostics | null
}

interface ChatStreamDelta {
  type: 'delta'
  text: string
}

type ChatStreamEvent = ChatStreamDelta | ChatStreamDone

/**
 * The send-message endpoint runs the full pipeline server-side (retrieval
 * -> generation -> faithfulness guardrail) before anything is safe to
 * show, then streams the already-validated answer text in chunks — see
 * api/v1/chat.py's module docstring for why this isn't token-by-token
 * straight from the LLM. `openapi-fetch` has no streaming-body support,
 * so this is a plain authenticated `fetch` reading the SSE body directly
 * rather than going through `apiClient`.
 */
export async function streamChatMessage(
  sessionId: string,
  content: string,
  { onDelta, signal }: { onDelta: (text: string) => void; signal?: AbortSignal },
): Promise<ChatStreamDone> {
  const response = await fetch(`${apiOrigin}/api/v1/chat/sessions/${sessionId}/messages`, {
    method: 'POST',
    credentials: 'include',
    signal,
    headers: {
      'Content-Type': 'application/json',
      ...(getAccessToken() ? { Authorization: `Bearer ${getAccessToken()}` } : {}),
    },
    body: JSON.stringify({ content }),
  })

  if (!response.ok || !response.body) {
    const detail = await response.json().catch(() => null)
    throw new Error(detail?.detail ?? `Chat request failed (${response.status}).`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let done: ChatStreamDone | null = null

  while (true) {
    const { value, done: streamDone } = await reader.read()
    if (streamDone) break
    buffer += decoder.decode(value, { stream: true })

    let separatorIndex: number
    while ((separatorIndex = buffer.indexOf('\n\n')) !== -1) {
      const rawEvent = buffer.slice(0, separatorIndex)
      buffer = buffer.slice(separatorIndex + 2)
      const dataLine = rawEvent.split('\n').find((line) => line.startsWith('data: '))
      if (!dataLine) continue

      const event = JSON.parse(dataLine.slice('data: '.length)) as ChatStreamEvent
      if (event.type === 'delta') {
        onDelta(event.text)
      } else {
        done = event
      }
    }
  }

  if (!done) throw new Error('Chat stream ended without a completion event.')
  return done
}
