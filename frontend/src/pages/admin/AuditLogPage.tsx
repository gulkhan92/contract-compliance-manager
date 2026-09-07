import { useQuery } from '@tanstack/react-query'

import { EmptyState, ErrorState, LoadingState } from '@/components/QueryState'
import { Badge } from '@/components/ui/badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { apiClient } from '@/lib/api-client'

export function AuditLogPage() {
  const { data, isPending, isError } = useQuery({
    queryKey: ['audit-log'],
    queryFn: async () => {
      const { data, error } = await apiClient.GET('/api/v1/audit-log', {
        params: { query: { limit: 100 } },
      })
      if (error) throw new Error('Failed to load the audit log.')
      return data
    },
  })

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Audit Log</h1>
        <p className="text-sm text-muted-foreground">
          Every state-changing action taken in your organization, most recent first.
        </p>
      </div>

      {isPending ? <LoadingState label="Loading audit log..." /> : null}
      {isError ? <ErrorState message="Could not load the audit log." /> : null}
      {data && data.length === 0 ? (
        <EmptyState title="No activity yet" description="Actions will appear here as they happen." />
      ) : null}

      {data && data.length > 0 ? (
        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>When</TableHead>
                <TableHead>Action</TableHead>
                <TableHead>Entity</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.map((entry) => (
                <TableRow key={entry.id}>
                  <TableCell className="text-sm tabular-nums whitespace-nowrap">
                    {new Date(entry.created_at).toLocaleString()}
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline">{entry.action}</Badge>
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {entry.entity_type}
                    {entry.entity_id ? ` · ${entry.entity_id.slice(0, 8)}` : ''}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      ) : null}
    </div>
  )
}
