import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { StatusBadge } from '@/components/StatusBadge'
import { EmptyState, ErrorState, LoadingState } from '@/components/QueryState'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { apiClient } from '@/lib/api-client'
import type { components } from '@/lib/api-schema'
import { OBLIGATION_STATUS_LABEL, OBLIGATION_STATUS_TONE, categoryLabel } from '@/lib/status'

type CalendarEntry = components['schemas']['CalendarEntry']

function groupByMonth(entries: CalendarEntry[]): [string, CalendarEntry[]][] {
  const groups = new Map<string, CalendarEntry[]>()
  for (const entry of entries) {
    const key = entry.trigger_date
      ? new Date(entry.trigger_date).toLocaleDateString(undefined, {
          month: 'long',
          year: 'numeric',
        })
      : 'No fixed date'
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push(entry)
  }
  return Array.from(groups.entries())
}

export function CalendarPage() {
  const [withinDays, setWithinDays] = useState('90')

  const { data, isPending, isError } = useQuery({
    queryKey: ['obligations-calendar', withinDays],
    queryFn: async () => {
      const { data, error } = await apiClient.GET('/api/v1/obligations/calendar', {
        params: { query: { within_days: Number(withinDays) } },
      })
      if (error) throw new Error('Failed to load the calendar.')
      return data
    },
  })

  const groups = useMemo(() => groupByMonth(data ?? []), [data])

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Compliance Calendar</h1>
          <p className="text-sm text-muted-foreground">
            Obligations due soon, or already overdue, across every contract.
          </p>
        </div>
        <Select value={withinDays} onValueChange={(value) => value && setWithinDays(value)}>
          <SelectTrigger className="w-44">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="30">Next 30 days</SelectItem>
            <SelectItem value="60">Next 60 days</SelectItem>
            <SelectItem value="90">Next 90 days</SelectItem>
            <SelectItem value="180">Next 180 days</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {isPending ? <LoadingState label="Loading calendar..." /> : null}
      {isError ? <ErrorState message="Could not load the calendar." /> : null}
      {data && data.length === 0 ? (
        <EmptyState
          title="Nothing due in this window"
          description="Try a longer time horizon, or check back later."
        />
      ) : null}

      <div className="flex flex-col gap-8">
        {groups.map(([month, entries]) => (
          <div key={month} className="flex flex-col gap-3">
            <h2 className="text-sm font-semibold text-muted-foreground">{month}</h2>
            <div className="flex flex-col divide-y rounded-lg border">
              {entries.map((entry) => (
                <div key={entry.id} className="flex items-center justify-between gap-4 p-4">
                  <div className="flex flex-col gap-1">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium tabular-nums">
                        {entry.trigger_date ?? 'No date'}
                      </span>
                      <StatusBadge
                        tone={OBLIGATION_STATUS_TONE[entry.status]}
                        label={OBLIGATION_STATUS_LABEL[entry.status]}
                      />
                    </div>
                    <p className="text-sm">{entry.description}</p>
                    <Link
                      to={`/contracts/${entry.contract_id}`}
                      className="text-xs text-muted-foreground hover:underline"
                    >
                      {entry.contract_title} · {categoryLabel(entry.category)}
                    </Link>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
