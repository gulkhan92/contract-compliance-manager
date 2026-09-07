import type { ReactNode } from 'react'

import { AlertCircle, Inbox, Loader2 } from 'lucide-react'

export function LoadingState({ label = 'Loading...' }: { label?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-16 text-muted-foreground">
      <Loader2 className="size-6 animate-spin" />
      <p className="text-sm">{label}</p>
    </div>
  )
}

export function ErrorState({
  message = "Something went wrong. Please try again.",
}: {
  message?: string
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-16 text-destructive">
      <AlertCircle className="size-6" />
      <p className="text-sm">{message}</p>
    </div>
  )
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string
  description?: string
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-16 text-center text-muted-foreground">
      <Inbox className="size-6" />
      <p className="text-sm font-medium text-foreground">{title}</p>
      {description ? <p className="max-w-sm text-sm">{description}</p> : null}
      {action}
    </div>
  )
}
