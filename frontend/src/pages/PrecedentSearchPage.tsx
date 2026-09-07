import { useState } from 'react'
import type { FormEvent } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Search } from 'lucide-react'

import { EmptyState, ErrorState, LoadingState } from '@/components/QueryState'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { apiClient } from '@/lib/api-client'

export function PrecedentSearchPage() {
  const [query, setQuery] = useState('')
  const [submittedQuery, setSubmittedQuery] = useState('')

  const { data, isPending, isError, isFetched } = useQuery({
    queryKey: ['precedent-search', submittedQuery],
    queryFn: async () => {
      const { data, error } = await apiClient.GET('/api/v1/precedents/search', {
        params: { query: { q: submittedQuery } },
      })
      if (error) throw new Error('Search failed.')
      return data
    },
    enabled: submittedQuery.length > 0,
  })

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setSubmittedQuery(query.trim())
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Precedent Search</h1>
        <p className="text-sm text-muted-foreground">
          Search across every clause your organization has ever ingested — find how similar
          terms were handled before.
        </p>
      </div>

      <form className="flex gap-2" onSubmit={handleSubmit}>
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="e.g. limitation of liability cap, 90 day termination notice..."
          className="max-w-xl"
        />
        <Button type="submit" disabled={!query.trim()}>
          <Search className="size-4" /> Search
        </Button>
      </form>

      {isPending && submittedQuery ? <LoadingState label="Searching..." /> : null}
      {isError ? <ErrorState message="Search failed. Please try again." /> : null}
      {isFetched && data && data.length === 0 ? (
        <EmptyState
          title="No matching clauses found"
          description="Try a different phrase, or upload more contracts to build up your precedent library."
        />
      ) : null}

      <div className="flex flex-col gap-3">
        {data?.map((result) => (
          <Card key={result.chunk_id}>
            <CardContent className="flex flex-col gap-2 py-4">
              <div className="flex items-center justify-between gap-2">
                <Link
                  to={`/contracts/${result.contract_id}`}
                  className="text-sm font-medium hover:underline"
                >
                  {result.contract_title}
                </Link>
                <span className="text-xs tabular-nums text-muted-foreground">
                  {Math.round(result.similarity * 100)}% match
                </span>
              </div>
              {result.section_heading ? (
                <p className="text-xs font-medium text-muted-foreground">
                  {result.section_heading}
                </p>
              ) : null}
              <p className="text-sm text-muted-foreground">{result.raw_text}</p>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}
