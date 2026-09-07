import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, CalendarClock, Clock, DollarSign } from 'lucide-react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  XAxis,
  YAxis,
} from 'recharts'

import { EmptyState, ErrorState, LoadingState } from '@/components/QueryState'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from '@/components/ui/chart'
import { apiClient } from '@/lib/api-client'
import { categoryLabel } from '@/lib/status'

function formatCurrency(amount: number, currency: string): string {
  try {
    return new Intl.NumberFormat(undefined, { style: 'currency', currency }).format(amount)
  } catch {
    return `${amount.toFixed(2)} ${currency}`
  }
}

const CATEGORY_CHART_CONFIG = {
  count: { label: 'Obligations', color: 'var(--chart-1)' },
} satisfies ChartConfig

const MONTH_CHART_CONFIG = {
  upcoming: { label: 'Upcoming', color: 'var(--chart-1)' },
  atRisk: { label: 'At risk', color: 'var(--chart-3)' },
  overdue: { label: 'Overdue', color: 'var(--chart-4)' },
} satisfies ChartConfig

export function DashboardPage() {
  const summaryQuery = useQuery({
    queryKey: ['dashboard-summary'],
    queryFn: async () => {
      const { data, error } = await apiClient.GET('/api/v1/dashboard/summary')
      if (error) throw new Error('Failed to load dashboard summary.')
      return data
    },
  })

  const obligationsQuery = useQuery({
    queryKey: ['obligations', { forDashboardCharts: true }],
    queryFn: async () => {
      const { data, error } = await apiClient.GET('/api/v1/obligations', {
        params: { query: { limit: 200 } },
      })
      if (error) throw new Error('Failed to load obligations.')
      return data
    },
  })

  const categoryChartData = useMemo(() => {
    const counts = new Map<string, number>()
    for (const o of obligationsQuery.data ?? []) {
      counts.set(o.category, (counts.get(o.category) ?? 0) + 1)
    }
    return Array.from(counts.entries())
      .map(([category, count]) => ({ category: categoryLabel(category), count }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 8)
  }, [obligationsQuery.data])

  const monthChartData = useMemo(() => {
    const buckets = new Map<string, { upcoming: number; atRisk: number; overdue: number }>()
    const now = new Date()
    for (let i = 0; i < 6; i++) {
      const d = new Date(now.getFullYear(), now.getMonth() + i, 1)
      buckets.set(d.toLocaleDateString(undefined, { month: 'short' }), {
        upcoming: 0,
        atRisk: 0,
        overdue: 0,
      })
    }
    for (const o of obligationsQuery.data ?? []) {
      if (!o.trigger_date) continue
      const key = new Date(o.trigger_date).toLocaleDateString(undefined, { month: 'short' })
      const bucket = buckets.get(key)
      if (!bucket) continue
      if (o.status === 'overdue') bucket.overdue += 1
      else if (o.status === 'at_risk') bucket.atRisk += 1
      else if (o.status === 'upcoming') bucket.upcoming += 1
    }
    return Array.from(buckets.entries()).map(([month, counts]) => ({ month, ...counts }))
  }, [obligationsQuery.data])

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
        <p className="text-sm text-muted-foreground">
          A live view of your organization&apos;s obligation compliance.
        </p>
      </div>

      {summaryQuery.isPending ? <LoadingState label="Loading dashboard..." /> : null}
      {summaryQuery.isError ? (
        <ErrorState message="Could not load the dashboard summary." />
      ) : null}

      {summaryQuery.data ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                At Risk
              </CardTitle>
              <AlertTriangle className="size-4 text-chart-3" />
            </CardHeader>
            <CardContent>
              <p className="text-3xl font-semibold tabular-nums">
                {summaryQuery.data.at_risk_count}
              </p>
              <p className="text-xs text-muted-foreground">obligations need attention soon</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Overdue
              </CardTitle>
              <Clock className="size-4 text-chart-4" />
            </CardHeader>
            <CardContent>
              <p className="text-3xl font-semibold tabular-nums">
                {summaryQuery.data.overdue_count}
              </p>
              <p className="text-xs text-muted-foreground">past their trigger date</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Upcoming This Month
              </CardTitle>
              <CalendarClock className="size-4 text-chart-1" />
            </CardHeader>
            <CardContent>
              <p className="text-3xl font-semibold tabular-nums">
                {summaryQuery.data.upcoming_this_month_count}
              </p>
              <p className="text-xs text-muted-foreground">due before month end</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Total Active Value
              </CardTitle>
              <DollarSign className="size-4 text-chart-2" />
            </CardHeader>
            <CardContent>
              {Object.keys(summaryQuery.data.total_active_contract_value).length === 0 ? (
                <p className="text-3xl font-semibold tabular-nums">—</p>
              ) : (
                Object.entries(summaryQuery.data.total_active_contract_value).map(
                  ([currency, amount]) => (
                    <p key={currency} className="text-3xl font-semibold tabular-nums">
                      {formatCurrency(amount, currency)}
                    </p>
                  ),
                )
              )}
              <p className="text-xs text-muted-foreground">across active contracts</p>
            </CardContent>
          </Card>
        </div>
      ) : null}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
        <Card className="lg:col-span-3">
          <CardHeader>
            <CardTitle>Obligations by category</CardTitle>
            <CardDescription>What kind of commitments your contracts actually carry</CardDescription>
          </CardHeader>
          <CardContent>
            {obligationsQuery.isPending ? <LoadingState label="Loading..." /> : null}
            {obligationsQuery.isError ? <ErrorState /> : null}
            {obligationsQuery.data && categoryChartData.length === 0 ? (
              <EmptyState title="No obligations yet" />
            ) : null}
            {categoryChartData.length > 0 ? (
              <ChartContainer config={CATEGORY_CHART_CONFIG} className="aspect-auto h-72 w-full">
                <BarChart data={categoryChartData} layout="vertical" margin={{ left: 8 }}>
                  <CartesianGrid horizontal={false} strokeDasharray="3 3" />
                  <XAxis type="number" allowDecimals={false} tickLine={false} axisLine={false} />
                  <YAxis
                    type="category"
                    dataKey="category"
                    tickLine={false}
                    axisLine={false}
                    width={140}
                    tick={{ fontSize: 12 }}
                  />
                  <ChartTooltip content={<ChartTooltipContent hideLabel />} />
                  <Bar dataKey="count" fill="var(--color-count)" radius={4} />
                </BarChart>
              </ChartContainer>
            ) : null}
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Next 6 months</CardTitle>
            <CardDescription>Obligations by trigger date and status</CardDescription>
          </CardHeader>
          <CardContent>
            {monthChartData.length > 0 ? (
              <ChartContainer config={MONTH_CHART_CONFIG} className="aspect-auto h-72 w-full">
                <BarChart data={monthChartData}>
                  <CartesianGrid vertical={false} strokeDasharray="3 3" />
                  <XAxis
                    dataKey="month"
                    tickLine={false}
                    axisLine={false}
                    tick={{ fontSize: 12 }}
                  />
                  <YAxis allowDecimals={false} tickLine={false} axisLine={false} width={28} />
                  <ChartTooltip content={<ChartTooltipContent />} />
                  <Bar dataKey="upcoming" stackId="a" fill="var(--color-upcoming)" radius={[0, 0, 0, 0]} />
                  <Bar dataKey="atRisk" stackId="a" fill="var(--color-atRisk)" radius={[0, 0, 0, 0]} />
                  <Bar dataKey="overdue" stackId="a" fill="var(--color-overdue)" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ChartContainer>
            ) : null}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
