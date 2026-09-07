import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, ExternalLink } from 'lucide-react'

import { ErrorState, LoadingState } from '@/components/QueryState'
import { Button } from '@/components/ui/button'
import { useContractFilePreview } from '@/hooks/useContractFilePreview'
import { apiClient } from '@/lib/api-client'

/**
 * Deliberately rendered outside AppShell (see App.tsx) — no sidebar, no
 * header chrome, just the document — because the whole point of this page
 * is that the previous inline preview was too small to read comfortably.
 */
export function ContractPreviewPage() {
  const { contractId } = useParams<{ contractId: string }>()

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

  const isPdf = contractQuery.data?.original_filename.toLowerCase().endsWith('.pdf') ?? false
  const preview = useContractFilePreview(contractId ?? '', !!contractId)

  return (
    <div className="flex h-svh flex-col">
      <header className="flex h-14 shrink-0 items-center gap-3 border-b bg-background px-4">
        <Button
          variant="ghost"
          size="icon"
          render={<Link to={`/contracts/${contractId}`} aria-label="Back to contract" />}
        >
          <ArrowLeft className="size-4" />
        </Button>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">
            {contractQuery.data?.title ?? 'Loading…'}
          </p>
          <p className="truncate text-xs text-muted-foreground">
            {contractQuery.data?.original_filename}
          </p>
        </div>
        {preview.url ? (
          <Button
            variant="outline"
            size="sm"
            render={<a href={preview.url} target="_blank" rel="noreferrer" />}
          >
            <ExternalLink className="size-4" />
            Open in new tab
          </Button>
        ) : null}
      </header>

      <main className="flex-1 overflow-hidden bg-muted/30">
        {!isPdf && contractQuery.data ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
            <p className="text-sm text-muted-foreground">
              Inline preview isn&apos;t available for DOCX files — browsers don&apos;t render
              them natively the way they do PDFs.
            </p>
            {preview.url ? (
              <Button render={<a href={preview.url} download={contractQuery.data.original_filename} />}>
                Download {contractQuery.data.original_filename}
              </Button>
            ) : null}
          </div>
        ) : preview.url ? (
          <iframe src={preview.url} title="Contract document" className="size-full border-0" />
        ) : preview.error ? (
          <div className="flex h-full items-center justify-center">
            <ErrorState message="Could not load the document preview." />
          </div>
        ) : (
          <div className="flex h-full items-center justify-center">
            <LoadingState label="Loading document..." />
          </div>
        )}
      </main>
    </div>
  )
}
