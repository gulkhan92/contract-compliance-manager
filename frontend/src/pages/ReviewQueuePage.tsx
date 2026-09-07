import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { Check, Pencil, X } from 'lucide-react'

import { ObligationEditDialog } from '@/components/ObligationEditDialog'
import { EmptyState, ErrorState, LoadingState } from '@/components/QueryState'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { apiClient } from '@/lib/api-client'
import type { components } from '@/lib/api-schema'
import { categoryLabel } from '@/lib/status'

type ObligationSummary = components['schemas']['ObligationSummary']

export function ReviewQueuePage() {
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState<ObligationSummary | null>(null)

  const { data, isPending, isError } = useQuery({
    queryKey: ['obligations', { needsReview: true }],
    queryFn: async () => {
      const { data, error } = await apiClient.GET('/api/v1/obligations', {
        params: { query: { limit: 200 } },
      })
      if (error) throw new Error('Failed to load the review queue.')
      return data.filter((o) => !o.is_human_reviewed)
    },
  })

  const invalidate = () => void queryClient.invalidateQueries({ queryKey: ['obligations'] })

  const confirmMutation = useMutation({
    mutationFn: async (id: string) =>
      apiClient.PATCH('/api/v1/obligations/{obligation_id}', {
        params: { path: { obligation_id: id } },
        body: {},
      }),
    onSuccess: (result) => {
      if (result.error) {
        toast.error('Could not confirm this obligation.')
        return
      }
      toast.success('Obligation confirmed.')
      invalidate()
    },
  })

  const waiveMutation = useMutation({
    mutationFn: async (id: string) =>
      apiClient.PATCH('/api/v1/obligations/{obligation_id}', {
        params: { path: { obligation_id: id } },
        body: { status: 'waived' },
      }),
    onSuccess: (result) => {
      if (result.error) {
        toast.error('Could not waive this obligation.')
        return
      }
      toast.success('Obligation waived.')
      invalidate()
    },
  })

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Review Queue</h1>
        <p className="text-sm text-muted-foreground">
          Low-confidence and high-stakes obligations (renewals, termination notices) awaiting
          human confirmation.
        </p>
      </div>

      {isPending ? <LoadingState label="Loading review queue..." /> : null}
      {isError ? <ErrorState message="Could not load the review queue." /> : null}
      {data && data.length === 0 ? (
        <EmptyState title="Nothing to review" description="Every obligation is up to date." />
      ) : null}

      <div className="flex flex-col gap-3">
        {data?.map((obligation) => (
          <Card key={obligation.id}>
            <CardContent className="flex items-start justify-between gap-4 py-4">
              <div className="flex flex-col gap-1">
                <div className="flex items-center gap-2">
                  <Badge variant="outline">{categoryLabel(obligation.category)}</Badge>
                  {obligation.confidence_score !== null ? (
                    <span className="text-xs text-muted-foreground">
                      {Math.round(obligation.confidence_score * 100)}% confidence
                    </span>
                  ) : null}
                </div>
                <p className="text-sm font-medium">{obligation.description}</p>
                <Link
                  to={`/contracts/${obligation.contract_id}`}
                  className="text-xs text-muted-foreground hover:underline"
                >
                  {obligation.contract_title}
                </Link>
                {obligation.trigger_date ? (
                  <p className="text-xs text-muted-foreground">
                    Trigger date: {obligation.trigger_date}
                  </p>
                ) : null}
              </div>
              <div className="flex shrink-0 gap-2">
                <Button
                  size="icon-sm"
                  variant="outline"
                  title="Confirm"
                  aria-label="Confirm obligation"
                  disabled={confirmMutation.isPending}
                  onClick={() => confirmMutation.mutate(obligation.id)}
                  className="hover:border-chart-2 hover:bg-chart-2/10 hover:text-chart-2"
                >
                  <Check className="size-4" />
                </Button>
                <Button
                  size="icon-sm"
                  variant="outline"
                  title="Edit"
                  aria-label="Edit obligation"
                  onClick={() => setEditing(obligation)}
                  className="hover:border-primary hover:bg-primary/10 hover:text-primary"
                >
                  <Pencil className="size-4" />
                </Button>
                <Button
                  size="icon-sm"
                  variant="outline"
                  title="Waive"
                  aria-label="Waive obligation"
                  disabled={waiveMutation.isPending}
                  onClick={() => waiveMutation.mutate(obligation.id)}
                  className="hover:border-destructive hover:bg-destructive/10 hover:text-destructive"
                >
                  <X className="size-4" />
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {editing ? (
        <ObligationEditDialog
          obligation={editing}
          open={!!editing}
          onOpenChange={(open) => !open && setEditing(null)}
          onSaved={invalidate}
        />
      ) : null}
    </div>
  )
}
