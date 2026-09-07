import { useEffect, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { MessageSquarePlus, Send, ShieldCheck, Trash2 } from 'lucide-react'
import { toast } from 'sonner'

import { ChatDisclaimer } from '@/components/chat/ChatDisclaimer'
import { ChatMessageBubble } from '@/components/chat/ChatMessageBubble'
import { CitationPanel } from '@/components/chat/CitationPanel'
import { EmptyState, ErrorState, LoadingState } from '@/components/QueryState'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { apiClient } from '@/lib/api-client'
import { streamChatMessage } from '@/lib/chat-stream'
import type { ChatStreamDone } from '@/lib/chat-stream'
import { cn } from '@/lib/utils'
import type { components } from '@/lib/api-schema'

type ChatCitation = components['schemas']['ChatCitation']

function useChatSessions() {
  return useQuery({
    queryKey: ['chat-sessions'],
    queryFn: async () => {
      const { data, error } = await apiClient.GET('/api/v1/chat/sessions')
      if (error) throw new Error('Failed to load chat sessions.')
      return data
    },
  })
}

function SessionSidebar({ activeSessionId }: { activeSessionId: string | undefined }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const sessionsQuery = useChatSessions()

  const createSession = useMutation({
    mutationFn: async () => {
      const { data, error } = await apiClient.POST('/api/v1/chat/sessions', {
        body: { scope: 'organization' },
      })
      if (error) throw new Error('Failed to start a new chat.')
      return data
    },
    onSuccess: (data) => {
      void queryClient.invalidateQueries({ queryKey: ['chat-sessions'] })
      navigate(`/chat/${data.id}`)
    },
    onError: () => toast.error('Could not start a new chat.'),
  })

  const deleteSession = useMutation({
    mutationFn: async (sessionId: string) => {
      const { error } = await apiClient.DELETE('/api/v1/chat/sessions/{session_id}', {
        params: { path: { session_id: sessionId } },
      })
      if (error) throw new Error('Failed to delete chat.')
    },
    onSuccess: (_data, sessionId) => {
      void queryClient.invalidateQueries({ queryKey: ['chat-sessions'] })
      if (sessionId === activeSessionId) navigate('/chat')
    },
    onError: () => toast.error('Could not delete chat.'),
  })

  return (
    <aside className="flex w-64 shrink-0 flex-col border-r bg-muted/20">
      <div className="flex h-14 shrink-0 items-center justify-between border-b px-3">
        <Link to="/dashboard" className="flex items-center gap-2 text-sm font-medium">
          <ShieldCheck className="size-4 text-primary" />
          ObliTrack
        </Link>
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={() => createSession.mutate()}
          disabled={createSession.isPending}
          aria-label="New chat"
        >
          <MessageSquarePlus className="size-4" />
        </Button>
      </div>
      <div className="flex-1 overflow-y-auto p-2">
        {sessionsQuery.isPending ? <LoadingState label="Loading chats..." /> : null}
        {sessionsQuery.data?.length === 0 ? (
          <p className="p-3 text-xs text-muted-foreground">
            No chats yet — start one with the button above.
          </p>
        ) : null}
        {sessionsQuery.data?.map((session) => (
          <div
            key={session.id}
            className={cn(
              'group flex items-center gap-1 rounded-md px-2 py-1.5',
              session.id === activeSessionId ? 'bg-sidebar-accent' : 'hover:bg-muted',
            )}
          >
            <Link to={`/chat/${session.id}`} className="min-w-0 flex-1">
              <p className="truncate text-sm">{session.title}</p>
              <p className="truncate text-xs text-muted-foreground">
                {session.scope === 'contract' ? 'This contract' : 'Organization-wide'}
              </p>
            </Link>
            <Button
              variant="ghost"
              size="icon-sm"
              className="opacity-0 group-hover:opacity-100"
              onClick={() => deleteSession.mutate(session.id)}
              aria-label="Delete chat"
            >
              <Trash2 className="size-3.5" />
            </Button>
          </div>
        ))}
      </div>
    </aside>
  )
}

interface StreamingState {
  userContent: string
  assistantText: string
  // Populated once the SSE 'done' event arrives — while null, only raw
  // deltas have landed and the bubble below shows plain streaming text.
  // Once set, citations/confidence/diagnostics are already known (the
  // pipeline validates everything server-side before streaming a single
  // byte — see chat.py's module docstring) and are rendered immediately,
  // rather than waiting for the post-send session refetch to reveal them.
  done: ChatStreamDone | null
}

function ChatThread({ sessionId }: { sessionId: string }) {
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState('')
  const [streaming, setStreaming] = useState<StreamingState | null>(null)
  const [activeCitation, setActiveCitation] = useState<ChatCitation | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  const sessionQuery = useQuery({
    queryKey: ['chat-session', sessionId],
    queryFn: async () => {
      const { data, error } = await apiClient.GET('/api/v1/chat/sessions/{session_id}', {
        params: { path: { session_id: sessionId } },
      })
      if (error) throw new Error('Failed to load this chat.')
      return data
    },
  })

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [sessionQuery.data?.messages, streaming])

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    const content = draft.trim()
    if (!content || streaming) return

    setDraft('')
    setStreaming({ userContent: content, assistantText: '', done: null })
    try {
      const done = await streamChatMessage(sessionId, content, {
        onDelta: (text) =>
          setStreaming((prev) => (prev ? { ...prev, assistantText: prev.assistantText + text } : prev)),
      })
      // Citations/confidence/diagnostics are already known here — render
      // them right away rather than leaving the bubble bare until the
      // refetch below resolves.
      setStreaming((prev) => (prev ? { ...prev, done } : prev))
      await queryClient.invalidateQueries({ queryKey: ['chat-session', sessionId] })
      await queryClient.invalidateQueries({ queryKey: ['chat-sessions'] })
    } catch {
      toast.error('That message failed to send. Please try again.')
    } finally {
      setStreaming(null)
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      event.currentTarget.form?.requestSubmit()
    }
  }

  if (sessionQuery.isPending) return <LoadingState label="Loading chat..." />
  if (sessionQuery.isError || !sessionQuery.data) {
    return <ErrorState message="Could not load this chat." />
  }

  const messages = sessionQuery.data.messages ?? []

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <ChatDisclaimer />
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-6">
        <div className="mx-auto flex max-w-2xl flex-col gap-4">
          {messages.length === 0 && !streaming ? (
            <EmptyState
              title="Ask about your contracts"
              description='Try "What is the termination notice period in our Acme NDA?" or "What obligations are overdue?"'
            />
          ) : null}
          {messages.map((message) => (
            <ChatMessageBubble
              key={message.id}
              message={message}
              sessionId={sessionId}
              onCitationClick={setActiveCitation}
            />
          ))}
          {streaming ? (
            <>
              <ChatMessageBubble
                message={{
                  id: 'pending-user',
                  role: 'user',
                  content: streaming.userContent,
                  confidence: null,
                  intent: null,
                  citations: null,
                  feedback: 'none',
                  created_at: new Date().toISOString(),
                }}
                sessionId={sessionId}
                onCitationClick={setActiveCitation}
              />
              {streaming.done ? (
                <ChatMessageBubble
                  message={{
                    id: streaming.done.message_id,
                    role: 'assistant',
                    content: streaming.assistantText,
                    confidence: streaming.done.confidence,
                    intent: streaming.done.intent,
                    citations: streaming.done.citations,
                    retrieval_diagnostics: streaming.done.retrieval_diagnostics,
                    feedback: 'none',
                    created_at: new Date().toISOString(),
                  }}
                  sessionId={sessionId}
                  onCitationClick={setActiveCitation}
                />
              ) : (
                <div className="flex justify-start">
                  <div className="max-w-[85%] rounded-2xl rounded-bl-sm border bg-card px-4 py-3">
                    <p className="whitespace-pre-wrap text-sm leading-relaxed">
                      {streaming.assistantText}
                      <span className="ml-0.5 inline-block h-3.5 w-1.5 animate-pulse bg-muted-foreground/50 align-middle" />
                    </p>
                  </div>
                </div>
              )}
            </>
          ) : null}
        </div>
      </div>
      <form onSubmit={handleSubmit} className="border-t p-4">
        <div className="mx-auto flex max-w-2xl items-end gap-2">
          <Textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about your contracts, obligations, or calendar..."
            rows={1}
            className="max-h-40 min-h-10 resize-none"
            disabled={!!streaming}
          />
          <Button type="submit" size="icon" disabled={!draft.trim() || !!streaming} aria-label="Send">
            <Send className="size-4" />
          </Button>
        </div>
      </form>
      <CitationPanel
        citation={activeCitation}
        open={activeCitation !== null}
        onOpenChange={(open) => !open && setActiveCitation(null)}
      />
    </div>
  )
}

export function ChatPage() {
  const { sessionId } = useParams<{ sessionId?: string }>()

  return (
    <div className="flex h-svh">
      <SessionSidebar activeSessionId={sessionId} />
      {sessionId ? (
        <ChatThread key={sessionId} sessionId={sessionId} />
      ) : (
        <div className="flex flex-1 items-center justify-center">
          <EmptyState
            title="Select or start a chat"
            description="Choose a conversation from the sidebar, or start a new one to ask about your contracts."
          />
        </div>
      )}
    </div>
  )
}
