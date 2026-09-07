import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ThumbsDown, ThumbsUp } from 'lucide-react'

import { ConfidenceBadge } from '@/components/chat/ConfidenceBadge'
import { MessageText } from '@/components/chat/MessageText'
import { RetrievalDiagnosticsPanel } from '@/components/chat/RetrievalDiagnosticsPanel'
import { Button } from '@/components/ui/button'
import { apiClient } from '@/lib/api-client'
import { CHAT_INTENT_LABEL } from '@/lib/status'
import { cn } from '@/lib/utils'
import type { components } from '@/lib/api-schema'

type ChatMessageSummary = components['schemas']['ChatMessageSummary']
type ChatCitation = components['schemas']['ChatCitation']

export function ChatMessageBubble({
  message,
  sessionId,
  onCitationClick,
}: {
  message: ChatMessageSummary
  sessionId: string
  onCitationClick: (citation: ChatCitation) => void
}) {
  const isUser = message.role === 'user'
  const queryClient = useQueryClient()

  const feedbackMutation = useMutation({
    mutationFn: async (feedback: 'up' | 'down') => {
      const { error } = await apiClient.PATCH('/api/v1/chat/messages/{message_id}/feedback', {
        params: { path: { message_id: message.id } },
        body: { feedback },
      })
      if (error) throw new Error('Failed to record feedback.')
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['chat-session', sessionId] })
    },
  })

  if (isUser) {
    return (
      <div className="flex justify-end">
        <div className="max-w-[75%] rounded-2xl rounded-br-sm bg-primary px-4 py-2.5 text-primary-foreground">
          <p className="whitespace-pre-wrap text-sm">{message.content}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex justify-start">
      <div className="flex max-w-[85%] flex-col gap-2 rounded-2xl rounded-bl-sm border bg-card px-4 py-3">
        <MessageText
          text={message.content}
          citations={message.citations ?? []}
          onCitationClick={onCitationClick}
        />
        <div className="flex flex-wrap items-center gap-2 pt-1">
          {message.confidence ? <ConfidenceBadge confidence={message.confidence} /> : null}
          {message.intent && message.intent !== 'domain_question' ? (
            <span className="text-xs text-muted-foreground">{CHAT_INTENT_LABEL[message.intent]}</span>
          ) : null}
          <div className="ml-auto flex items-center gap-0.5">
            <Button
              variant="ghost"
              size="icon-sm"
              className={cn(message.feedback === 'up' && 'text-emerald-600 dark:text-emerald-400')}
              disabled={feedbackMutation.isPending}
              onClick={() => feedbackMutation.mutate('up')}
              aria-label="Good response"
            >
              <ThumbsUp className="size-3.5" />
            </Button>
            <Button
              variant="ghost"
              size="icon-sm"
              className={cn(message.feedback === 'down' && 'text-destructive')}
              disabled={feedbackMutation.isPending}
              onClick={() => feedbackMutation.mutate('down')}
              aria-label="Poor response"
            >
              <ThumbsDown className="size-3.5" />
            </Button>
          </div>
        </div>
        {message.confidence === 'insufficient_information' && message.retrieval_diagnostics ? (
          <RetrievalDiagnosticsPanel diagnostics={message.retrieval_diagnostics} />
        ) : null}
      </div>
    </div>
  )
}
