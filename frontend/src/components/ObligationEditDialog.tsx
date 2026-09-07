import { useState } from 'react'
import type { FormEvent } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { apiClient } from '@/lib/api-client'
import type { components } from '@/lib/api-schema'
import { OBLIGATION_STATUS_LABEL, categoryLabel } from '@/lib/status'

type ObligationSummary = components['schemas']['ObligationSummary']
type ObligationCategory = components['schemas']['ObligationCategory']
type ObligationStatus = components['schemas']['ObligationStatus']

const CATEGORIES: ObligationCategory[] = [
  'RENEWAL',
  'TERMINATION_NOTICE',
  'PAYMENT_MILESTONE',
  'SLA_COMMITMENT',
  'INDEMNIFICATION',
  'CONFIDENTIALITY',
  'NON_COMPETE',
  'LIMITATION_OF_LIABILITY',
  'GOVERNING_LAW',
  'AUDIT_RIGHTS',
  'DATA_PROTECTION',
  'OTHER_OBLIGATION',
]

const STATUSES: ObligationStatus[] = ['upcoming', 'at_risk', 'overdue', 'resolved', 'waived']

export function ObligationEditDialog({
  obligation,
  open,
  onOpenChange,
  onSaved,
}: {
  obligation: ObligationSummary
  open: boolean
  onOpenChange: (open: boolean) => void
  onSaved: () => void
}) {
  const [category, setCategory] = useState<ObligationCategory>(obligation.category)
  const [description, setDescription] = useState(obligation.description)
  const [triggerDate, setTriggerDate] = useState(obligation.trigger_date ?? '')
  const [noticePeriodDays, setNoticePeriodDays] = useState(
    obligation.notice_period_days?.toString() ?? '',
  )
  const [status, setStatus] = useState<ObligationStatus>(obligation.status)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setIsSubmitting(true)
    setError(null)

    const { error: patchError } = await apiClient.PATCH('/api/v1/obligations/{obligation_id}', {
      params: { path: { obligation_id: obligation.id } },
      body: {
        category,
        description,
        trigger_date: triggerDate || null,
        notice_period_days: noticePeriodDays ? Number(noticePeriodDays) : null,
        status,
      },
    })

    setIsSubmitting(false)
    if (patchError) {
      setError('Could not save your changes.')
      return
    }
    toast.success('Obligation updated.')
    onOpenChange(false)
    onSaved()
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Edit obligation</DialogTitle>
          <DialogDescription>{obligation.contract_title}</DialogDescription>
        </DialogHeader>
        <form className="flex flex-col gap-4" onSubmit={(e) => void handleSubmit(e)}>
          <div className="flex flex-col gap-2">
            <Label>Category</Label>
            <Select value={category} onValueChange={(v) => setCategory(v as ObligationCategory)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {CATEGORIES.map((c) => (
                  <SelectItem key={c} value={c}>
                    {categoryLabel(c)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="flex flex-col gap-2">
            <Label htmlFor="description">Description</Label>
            <Textarea
              id="description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="flex flex-col gap-2">
              <Label htmlFor="trigger-date">Trigger date</Label>
              <Input
                id="trigger-date"
                type="date"
                value={triggerDate}
                onChange={(e) => setTriggerDate(e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="notice-period">Notice period (days)</Label>
              <Input
                id="notice-period"
                type="number"
                min={0}
                value={noticePeriodDays}
                onChange={(e) => setNoticePeriodDays(e.target.value)}
              />
            </div>
          </div>

          <div className="flex flex-col gap-2">
            <Label>Status</Label>
            <Select value={status} onValueChange={(v) => setStatus(v as ObligationStatus)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {STATUSES.map((s) => (
                  <SelectItem key={s} value={s}>
                    {OBLIGATION_STATUS_LABEL[s]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {error ? <p className="text-sm text-destructive">{error}</p> : null}

          <DialogFooter>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? 'Saving...' : 'Save changes'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
