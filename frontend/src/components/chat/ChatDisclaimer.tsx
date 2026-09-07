import { Info } from 'lucide-react'

/**
 * Persistent, non-dismissible — plan §5 is explicit that this must be
 * present on every screen the assistant appears on, not a one-time toast
 * a user can miss or click away.
 */
export function ChatDisclaimer() {
  return (
    <div className="flex shrink-0 items-center gap-2 border-b bg-muted/40 px-4 py-2 text-xs text-muted-foreground">
      <Info className="size-3.5 shrink-0" />
      <p>
        This assistant summarizes and locates language in your organization&apos;s own contracts.
        It does not provide legal advice.
      </p>
    </div>
  )
}
