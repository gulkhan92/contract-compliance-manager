import { ExternalLink } from 'lucide-react'
import { Link } from 'react-router-dom'

import { Button } from '@/components/ui/button'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import type { components } from '@/lib/api-schema'

type ChatCitation = components['schemas']['ChatCitation']

/**
 * The side panel plan §5 describes for a clicked citation. "View in
 * document" opens the existing full-page PDF viewer (reusing that
 * traceability rather than building a new one, per the plan) — it does
 * not scroll to or highlight the specific paragraph, since the current
 * viewer is a plain PDF iframe with no paragraph-anchor support; the
 * excerpt shown here is what stands in for that until a PDF-aware
 * viewer exists to highlight into.
 */
export function CitationPanel({
  citation,
  open,
  onOpenChange,
}: {
  citation: ChatCitation | null
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="flex flex-col">
        <SheetHeader>
          <SheetTitle className="pr-6">{citation?.contract_title}</SheetTitle>
          <SheetDescription>
            {citation?.is_reference_corpus
              ? "From the CUAD reference corpus — not one of your organization's own contracts, so there's no document to open here."
              : 'Source excerpt this citation was grounded in.'}
          </SheetDescription>
        </SheetHeader>
        <div className="flex-1 overflow-y-auto px-4">
          <p className="rounded-md border bg-muted/40 p-3 text-sm text-muted-foreground">
            {citation?.snippet}
          </p>
        </div>
        {citation && !citation.is_reference_corpus && citation.contract_id ? (
          <SheetFooter>
            <Button render={<Link to={`/contracts/${citation.contract_id}/preview`} />}>
              <ExternalLink className="size-4" />
              View in document
            </Button>
          </SheetFooter>
        ) : null}
      </SheetContent>
    </Sheet>
  )
}
