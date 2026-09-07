import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { apiClient } from '@/lib/api-client'

/**
 * The network fetch goes through TanStack Query — not a hand-rolled
 * useEffect — specifically so concurrent/duplicate mounts (React
 * StrictMode's dev-only double-invoke, or navigating between the detail
 * page and the full-page preview for the same contract) share one cached
 * fetch of the file's bytes instead of each re-downloading the whole PDF.
 * Object URLs are still inherently imperative browser state, so a small
 * effect derives one from the cached blob and revokes it on change/unmount.
 */
export function useContractFilePreview(contractId: string, enabled: boolean) {
  const blobQuery = useQuery({
    queryKey: ['contract-file', contractId],
    queryFn: async () => {
      const { data, error } = await apiClient.GET('/api/v1/contracts/{contract_id}/file', {
        params: { path: { contract_id: contractId } },
        parseAs: 'blob',
      })
      if (error || !data) throw new Error('Failed to load file')
      return data as Blob
    },
    enabled: enabled && !!contractId,
    staleTime: 5 * 60_000,
    gcTime: 10 * 60_000,
  })

  const [url, setUrl] = useState<string | null>(null)

  useEffect(() => {
    if (!blobQuery.data) {
      setUrl(null)
      return
    }
    const objectUrl = URL.createObjectURL(blobQuery.data)
    setUrl(objectUrl)
    return () => URL.revokeObjectURL(objectUrl)
  }, [blobQuery.data])

  return { url, error: blobQuery.isError }
}
