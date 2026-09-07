import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { PlayCircle } from 'lucide-react'

import { ErrorState, LoadingState } from '@/components/QueryState'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import { apiClient } from '@/lib/api-client'

function providerLabel(provider: string): string {
  return provider === 'groq' ? 'Groq' : 'Gemini'
}

export function LLMUsagePage() {
  const queryClient = useQueryClient()
  const [lastScanMessage, setLastScanMessage] = useState<string | null>(null)

  const { data, isPending, isError } = useQuery({
    queryKey: ['llm-usage'],
    queryFn: async () => {
      const { data, error } = await apiClient.GET('/api/v1/admin/llm-usage')
      if (error) throw new Error('Failed to load LLM usage.')
      return data
    },
  })

  const scanMutation = useMutation({
    mutationFn: async () => {
      const { data, error } = await apiClient.POST('/api/v1/admin/alerts/scan')
      if (error) throw new Error('Scan failed.')
      return data
    },
    onSuccess: (result) => {
      setLastScanMessage(
        `Recomputed ${result.statuses_recomputed} statuses. Sent ${result.alerts_sent} alerts` +
          `${result.alerts_failed ? `, ${result.alerts_failed} failed` : ''}` +
          `${result.alerts_skipped_duplicate ? `, ${result.alerts_skipped_duplicate} already sent today` : ''}.`,
      )
      toast.success('Alert scan complete.')
      void queryClient.invalidateQueries({ queryKey: ['llm-usage'] })
    },
    onError: () => toast.error('Alert scan failed.'),
  })

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">LLM Usage</h1>
          <p className="text-sm text-muted-foreground">
            Today&apos;s Groq/Gemini quota consumption from the dual-provider extraction pipeline.
          </p>
        </div>
        <Button onClick={() => scanMutation.mutate()} disabled={scanMutation.isPending}>
          <PlayCircle className="size-4" />
          {scanMutation.isPending ? 'Running scan...' : 'Run alert scan now'}
        </Button>
      </div>

      {lastScanMessage ? (
        <p className="text-sm text-muted-foreground">{lastScanMessage}</p>
      ) : null}

      {isPending ? <LoadingState label="Loading usage..." /> : null}
      {isError ? <ErrorState message="Could not load LLM usage." /> : null}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {data?.map((usage) => (
          <Card key={usage.provider}>
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle>{providerLabel(usage.provider)}</CardTitle>
              <Badge variant={usage.has_headroom ? 'secondary' : 'destructive'}>
                {usage.has_headroom ? 'Available' : 'No headroom'}
              </Badge>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              <div className="flex flex-col gap-1.5">
                <div className="flex justify-between text-xs text-muted-foreground">
                  <span>Requests</span>
                  <span className="tabular-nums">
                    {usage.requests_used} / {usage.requests_limit}
                  </span>
                </div>
                <Progress value={(usage.requests_used / usage.requests_limit) * 100} />
              </div>
              <div className="flex flex-col gap-1.5">
                <div className="flex justify-between text-xs text-muted-foreground">
                  <span>Tokens</span>
                  <span className="tabular-nums">
                    {usage.tokens_used.toLocaleString()} / {usage.tokens_limit.toLocaleString()}
                  </span>
                </div>
                <Progress value={(usage.tokens_used / usage.tokens_limit) * 100} />
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}
