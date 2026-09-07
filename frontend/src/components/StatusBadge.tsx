import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import type { BadgeTone } from '@/lib/status'

const TONE_CLASSES: Record<BadgeTone, string> = {
  neutral: 'bg-muted text-muted-foreground',
  info: 'bg-blue-500/10 text-blue-600 dark:text-blue-400',
  warning: 'bg-amber-500/10 text-amber-600 dark:text-amber-400',
  danger: 'bg-destructive/10 text-destructive',
  success: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400',
}

export function StatusBadge({ tone, label }: { tone: BadgeTone; label: string }) {
  return (
    <Badge variant="secondary" className={cn('border-0', TONE_CLASSES[tone])}>
      {label}
    </Badge>
  )
}
