import { useMutation, useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { MessageSquare, Maximize2 } from 'lucide-react'
import { toast } from 'sonner'

import { EmptyState, ErrorState, LoadingState } from '@/components/QueryState'
import { StatusBadge } from '@/components/StatusBadge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import { useContractFilePreview } from '@/hooks/useContractFilePreview'
import { apiClient } from '@/lib/api-client'
import { CONTRACT_STATUS_LABEL, CONTRACT_STATUS_TONE, categoryLabel } from '@/lib/status'

export function ContractDetailPage() {
  const { contractId } = useParams<{ contractId: string }>()
  const navigate = useNavigate()

  const startChat = useMutation({
    mutationFn: async () => {
      const { data, error } = await apiClient.POST('/api/v1/chat/sessions', {
        body: { scope: 'contract', contract_id: contractId! },
      })
      if (error) throw new Error('Failed to start a chat about this contract.')
      return data
    },
    onSuccess: (data) => navigate(`/chat/${data.id}`),
    onError: () => toast.error('Could not start a chat about this contract.'),
  })

  const contractQuery = useQuery({
    queryKey: ['contract', contractId],
    queryFn: async () => {
      const { data, error } = await apiClient.GET('/api/v1/contracts/{contract_id}', {
        params: { path: { contract_id: contractId! } },
      })
      if (error) throw new Error('Failed to load contract.')
      return data
    },
    enabled: !!contractId,
  })

  const statusQuery = useQuery({
    queryKey: ['contract-status', contractId],
    queryFn: async () => {
      const { data, error } = await apiClient.GET('/api/v1/contracts/{contract_id}/status', {
        params: { path: { contract_id: contractId! } },
      })
      if (error) throw new Error('Failed to load extraction status.')
      return data
    },
    enabled: !!contractId,
    refetchInterval: (query) => {
      const job = query.state.data?.latest_extraction_job
      return job && (job.status === 'queued' || job.status === 'running') ? 3000 : false
    },
  })

  const obligationsQuery = useQuery({
    queryKey: ['obligations', { contractId }],
    queryFn: async () => {
      const { data, error } = await apiClient.GET('/api/v1/obligations', {
        params: { query: { contract_id: contractId! } },
      })
      if (error) throw new Error('Failed to load obligations.')
      return data
    },
    enabled: !!contractId,
  })

  const isPdf = contractQuery.data?.original_filename.toLowerCase().endsWith('.pdf') ?? false
  const preview = useContractFilePreview(contractId ?? '', isPdf && !!contractId)

  if (contractQuery.isPending) return <LoadingState label="Loading contract..." />
  if (contractQuery.isError || !contractQuery.data) {
    return <ErrorState message="Could not load this contract." />
  }

  const contract = contractQuery.data

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{contract.title}</h1>
          <p className="text-sm text-muted-foreground">{contract.original_filename}</p>
        </div>
        <div className="flex shrink-0 items-center gap-3">
          <Button
            variant="outline"
            size="sm"
            onClick={() => startChat.mutate()}
            disabled={startChat.isPending}
          >
            <MessageSquare className="size-4" />
            Chat about this contract
          </Button>
          <StatusBadge
            tone={CONTRACT_STATUS_TONE[contract.status]}
            label={CONTRACT_STATUS_LABEL[contract.status]}
          />
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle className="text-sm text-muted-foreground">Counterparty</CardTitle>
          </CardHeader>
          <CardContent className="text-sm font-medium">
            {contract.counterparty_name ?? '—'}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-sm text-muted-foreground">Effective / Expires</CardTitle>
          </CardHeader>
          <CardContent className="text-sm font-medium">
            {contract.effective_date ?? '—'} → {contract.original_expiration_date ?? '—'}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-sm text-muted-foreground">Governing Law</CardTitle>
          </CardHeader>
          <CardContent className="text-sm font-medium">
            {contract.governing_law ?? '—'}
          </CardContent>
        </Card>
      </div>

      {statusQuery.data?.latest_extraction_job ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Extraction status</CardTitle>
          </CardHeader>
          <CardContent className="flex items-center gap-3 text-sm">
            <Badge variant="outline">{statusQuery.data.latest_extraction_job.status}</Badge>
            {statusQuery.data.latest_extraction_job.llm_provider_used ? (
              <span className="text-muted-foreground">
                via {statusQuery.data.latest_extraction_job.llm_provider_used}
              </span>
            ) : null}
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>Document preview</CardTitle>
          {isPdf && contractId ? (
            <Button
              variant="outline"
              size="sm"
              render={<Link to={`/contracts/${contractId}/preview`} />}
            >
              <Maximize2 className="size-4" />
              Full page view
            </Button>
          ) : null}
        </CardHeader>
        <CardContent>
          {isPdf ? (
            preview.url ? (
              <iframe
                src={preview.url}
                title="Contract document"
                className="h-[85vh] w-full rounded-md border"
              />
            ) : preview.error ? (
              <ErrorState message="Could not load the document preview." />
            ) : (
              <LoadingState label="Loading document..." />
            )
          ) : (
            <p className="py-8 text-center text-sm text-muted-foreground">
              Inline preview isn&apos;t available for DOCX files.
            </p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Extracted obligations</CardTitle>
        </CardHeader>
        <CardContent>
          {obligationsQuery.isPending ? <LoadingState label="Loading obligations..." /> : null}
          {obligationsQuery.isError ? <ErrorState message="Could not load obligations." /> : null}
          {obligationsQuery.data && obligationsQuery.data.length === 0 ? (
            <EmptyState
              title="No obligations extracted yet"
              description="Extraction may still be in progress, or no obligations were found."
            />
          ) : null}
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {obligationsQuery.data?.map((obligation) => (
              <div key={obligation.id} className="flex flex-col gap-1 rounded-lg border p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium">{categoryLabel(obligation.category)}</span>
                  <Badge variant={obligation.is_human_reviewed ? 'secondary' : 'outline'}>
                    {obligation.is_human_reviewed ? 'Reviewed' : 'Needs review'}
                  </Badge>
                </div>
                <p className="text-sm text-muted-foreground">{obligation.description}</p>
                {obligation.trigger_date ? (
                  <p className="text-xs text-muted-foreground">
                    Trigger date: {obligation.trigger_date}
                  </p>
                ) : null}
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <Separator />
    </div>
  )
}
