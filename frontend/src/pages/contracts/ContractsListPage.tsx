import { useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { Plus, Upload } from 'lucide-react'

import { EmptyState, ErrorState, LoadingState } from '@/components/QueryState'
import { StatusBadge } from '@/components/StatusBadge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
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
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { apiClient } from '@/lib/api-client'
import type { components } from '@/lib/api-schema'
import { CONTRACT_STATUS_LABEL, CONTRACT_STATUS_TONE } from '@/lib/status'

type ContractType = components['schemas']['ContractType']

const CONTRACT_TYPES: ContractType[] = [
  'NDA',
  'MSA',
  'Lease',
  'License',
  'Employment',
  'Vendor',
  'Other',
]

function UploadDialog({ onUploaded }: { onUploaded: () => void }) {
  const [open, setOpen] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [title, setTitle] = useState('')
  const [contractType, setContractType] = useState<ContractType>('Other')
  const [isDragging, setIsDragging] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function reset() {
    setFile(null)
    setTitle('')
    setContractType('Other')
    setError(null)
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (!file) {
      setError('Choose a PDF or DOCX file to upload.')
      return
    }
    setIsSubmitting(true)
    setError(null)

    const formData = new FormData()
    formData.append('file', file)
    formData.append('contract_type', contractType)
    if (title) formData.append('title', title)

    const { error: uploadError } = await apiClient.POST('/api/v1/contracts', {
      // openapi-fetch passes FormData straight through; the generated
      // request-body type models the multipart schema as a plain object,
      // so this cast documents an intentional, known-safe mismatch.
      body: formData as unknown as { file: string; contract_type: ContractType },
    })

    setIsSubmitting(false)
    if (uploadError) {
      const detail = (uploadError as { detail?: string }).detail
      setError(detail ?? 'Upload failed. Please try again.')
      return
    }

    toast.success('Contract uploaded — extraction is running in the background.')
    setOpen(false)
    reset()
    onUploaded()
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (!next) reset()
      }}
    >
      <DialogTrigger render={<Button><Plus className="size-4" /> Upload contract</Button>} />
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Upload a contract</DialogTitle>
          <DialogDescription>PDF or DOCX, up to 20MB.</DialogDescription>
        </DialogHeader>
        <form className="flex flex-col gap-4" onSubmit={(e) => void handleSubmit(e)}>
          <div
            className={`flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed p-8 text-center text-sm transition-colors ${
              isDragging ? 'border-primary bg-primary/5' : 'border-border'
            }`}
            onDragOver={(e) => {
              e.preventDefault()
              setIsDragging(true)
            }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={(e) => {
              e.preventDefault()
              setIsDragging(false)
              const dropped = e.dataTransfer.files[0]
              if (dropped) setFile(dropped)
            }}
          >
            <Upload className="size-6 text-muted-foreground" />
            {file ? (
              <p className="font-medium">{file.name}</p>
            ) : (
              <p className="text-muted-foreground">Drag a file here, or</p>
            )}
            <button
              type="button"
              className="cursor-pointer text-primary underline-offset-4 hover:underline"
              onClick={() => fileInputRef.current?.click()}
            >
              browse files
            </button>
            <Input
              ref={fileInputRef}
              id="file-input"
              type="file"
              accept=".pdf,.docx"
              className="hidden"
              aria-label="Contract file"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </div>

          <div className="flex flex-col gap-2">
            <Label htmlFor="title">Title (optional)</Label>
            <Input
              id="title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Defaults to the filename"
            />
          </div>

          <div className="flex flex-col gap-2">
            <Label>Contract type</Label>
            <Select value={contractType} onValueChange={(v) => setContractType(v as ContractType)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {CONTRACT_TYPES.map((type) => (
                  <SelectItem key={type} value={type}>
                    {type}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {error ? <p className="text-sm text-destructive">{error}</p> : null}

          <DialogFooter>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? 'Uploading...' : 'Upload'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

export function ContractsListPage() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [statusFilter, setStatusFilter] = useState<string>('all')

  const { data, isPending, isError } = useQuery({
    queryKey: ['contracts', statusFilter],
    queryFn: async () => {
      const { data, error } = await apiClient.GET('/api/v1/contracts', {
        params: {
          query: statusFilter === 'all' ? {} : { status: statusFilter as never },
        },
      })
      if (error) throw new Error('Failed to load contracts.')
      return data
    },
  })

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Contracts</h1>
          <p className="text-sm text-muted-foreground">
            Every contract your organization has uploaded.
          </p>
        </div>
        <UploadDialog
          onUploaded={() => void queryClient.invalidateQueries({ queryKey: ['contracts'] })}
        />
      </div>

      <div className="flex items-center gap-2">
        <Select value={statusFilter} onValueChange={(value) => value && setStatusFilter(value)}>
          <SelectTrigger className="w-48">
            <SelectValue placeholder="Filter by status" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All statuses</SelectItem>
            {Object.entries(CONTRACT_STATUS_LABEL).map(([value, label]) => (
              <SelectItem key={value} value={value}>
                {label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {isPending ? <LoadingState label="Loading contracts..." /> : null}
      {isError ? <ErrorState message="Could not load contracts." /> : null}

      {data && data.length === 0 ? (
        <EmptyState
          title="No contracts yet"
          description="Upload your first contract to start extracting obligations automatically."
        />
      ) : null}

      {data && data.length > 0 ? (
        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[34%]">Title</TableHead>
                <TableHead className="w-[26%]">Counterparty</TableHead>
                <TableHead className="w-[14%]">Type</TableHead>
                <TableHead className="w-[14%]">Status</TableHead>
                <TableHead className="w-[12%]">Expiration</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.map((contract) => (
                <TableRow
                  key={contract.id}
                  className="cursor-pointer"
                  onClick={() => navigate(`/contracts/${contract.id}`)}
                >
                  <TableCell className="max-w-0 font-medium">
                    <span className="block truncate" title={contract.title}>
                      {contract.title}
                    </span>
                  </TableCell>
                  <TableCell className="max-w-0 text-muted-foreground">
                    <span className="block truncate" title={contract.counterparty_name ?? undefined}>
                      {contract.counterparty_name ?? '—'}
                    </span>
                  </TableCell>
                  <TableCell className="text-muted-foreground">{contract.contract_type}</TableCell>
                  <TableCell>
                    <StatusBadge
                      tone={CONTRACT_STATUS_TONE[contract.status]}
                      label={CONTRACT_STATUS_LABEL[contract.status]}
                    />
                  </TableCell>
                  <TableCell className="text-muted-foreground tabular-nums">
                    {contract.original_expiration_date ?? '—'}
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
