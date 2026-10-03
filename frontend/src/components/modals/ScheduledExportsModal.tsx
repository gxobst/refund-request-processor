import * as React from 'react'
import {
  Calendar,
  Clock,
  Mail,
  Play,
  Trash2,
  Plus,
  Loader2,
  CheckCircle,
  AlertCircle,
  FileSpreadsheet,
} from 'lucide-react'
import {
  Dialog,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/Dialog'
import { Button } from '@/components/ui/Button'
import { cn } from '@/lib/utils'
import type { ExportSchedule } from '@/types/api'
import {
  fetchExportSchedules,
  createExportSchedule,
  updateExportSchedule,
  deleteExportSchedule,
  triggerExportSchedule,
} from '@/services/scheduleExportService'

export interface ScheduledExportsModalProps {
  isOpen: boolean
  onClose: () => void
}

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export function ScheduledExportsModal({
  isOpen,
  onClose,
}: ScheduledExportsModalProps) {
  const [schedules, setSchedules] = React.useState<ExportSchedule[]>([])
  const [isLoading, setIsLoading] = React.useState<boolean>(false)
  const [loadError, setLoadError] = React.useState<string | null>(null)

  // Form states
  const [name, setName] = React.useState<string>('')
  const [recipientsText, setRecipientsText] = React.useState<string>('')
  const [frequency, setFrequency] = React.useState<'daily' | 'weekly'>('daily')
  const [format, setFormat] = React.useState<'csv' | 'json'>('csv')
  const [isSubmitting, setIsSubmitting] = React.useState<boolean>(false)
  const [formError, setFormError] = React.useState<string | null>(null)

  // Action states per schedule
  const [triggeringId, setTriggeringId] = React.useState<string | null>(null)
  const [triggerFeedback, setTriggerFeedback] = React.useState<{
    [id: string]: { type: 'success' | 'error'; message: string }
  }>({})
  const [deletingId, setDeletingId] = React.useState<string | null>(null)

  // Load schedules on modal open
  React.useEffect(() => {
    if (!isOpen) {
      setFormError(null)
      setTriggerFeedback({})
      return
    }

    let isMounted = true
    async function loadData() {
      setIsLoading(true)
      setLoadError(null)
      try {
        const data = await fetchExportSchedules()
        if (isMounted) {
          setSchedules(data)
        }
      } catch (err: unknown) {
        if (isMounted) {
          setLoadError(
            err instanceof Error ? err.message : 'Failed to load export schedules.'
          )
        }
      } finally {
        if (isMounted) {
          setIsLoading(false)
        }
      }
    }

    loadData()
    return () => {
      isMounted = false
    }
  }, [isOpen])

  // Form submit handler
  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    setFormError(null)

    const trimmedName = name.trim()
    if (!trimmedName) {
      setFormError('Schedule name is required.')
      return
    }

    const recipientsList = recipientsText
      .split(/[\n,]+/)
      .map((r) => r.trim())
      .filter(Boolean)

    if (recipientsList.length === 0) {
      setFormError('At least one recipient email address is required.')
      return
    }

    const invalidEmails = recipientsList.filter((email) => !EMAIL_REGEX.test(email))
    if (invalidEmails.length > 0) {
      setFormError(`Invalid email address format: ${invalidEmails.join(', ')}`)
      return
    }

    setIsSubmitting(true)
    try {
      const created = await createExportSchedule({
        name: trimmedName,
        recipients: recipientsList,
        frequency,
        format,
        enabled: true,
      })

      setSchedules((prev) => [...prev, created])
      setName('')
      setRecipientsText('')
      setFrequency('daily')
      setFormat('csv')
      setFormError(null)
    } catch (err: unknown) {
      setFormError(
        err instanceof Error ? err.message : 'Failed to create export schedule.'
      )
    } finally {
      setIsSubmitting(false)
    }
  }

  // Toggle enabled handler
  const handleToggleEnabled = async (sch: ExportSchedule) => {
    const id = sch.schedule_id || sch.scheduleId || ''
    const newEnabled = !sch.enabled
    try {
      const updated = await updateExportSchedule(id, { enabled: newEnabled })
      setSchedules((prev) =>
        prev.map((s) => ((s.schedule_id || s.scheduleId) === id ? updated : s))
      )
    } catch (err: unknown) {
      // optimistic rollback if needed or show feedback
      console.error('Failed to update schedule status', err)
    }
  }

  // Trigger Run Now handler
  const handleTrigger = async (sch: ExportSchedule) => {
    const id = sch.schedule_id || sch.scheduleId || ''
    setTriggeringId(id)
    setTriggerFeedback((prev) => ({ ...prev, [id]: undefined! }))

    try {
      const result = await triggerExportSchedule(id)
      setTriggerFeedback((prev) => ({
        ...prev,
        [id]: {
          type: 'success',
          message: `Dispatched to ${result.recipients_delivered.length} recipient(s) (${result.records_exported} records).`,
        },
      }))
      // Update last_run and last_status in local list
      setSchedules((prev) =>
        prev.map((s) =>
          (s.schedule_id || s.scheduleId) === id
            ? { ...s, last_run: result.executed_at, last_status: 'success' }
            : s
        )
      )
    } catch (err: unknown) {
      setTriggerFeedback((prev) => ({
        ...prev,
        [id]: {
          type: 'error',
          message: err instanceof Error ? err.message : 'Delivery trigger failed.',
        },
      }))
    } finally {
      setTriggeringId(null)
    }
  }

  // Delete schedule handler
  const handleDelete = async (sch: ExportSchedule) => {
    const id = sch.schedule_id || sch.scheduleId || ''
    setDeletingId(id)
    try {
      await deleteExportSchedule(id)
      setSchedules((prev) =>
        prev.filter((s) => (s.schedule_id || s.scheduleId) !== id)
      )
    } catch (err: unknown) {
      console.error('Failed to delete schedule', err)
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <Dialog
      isOpen={isOpen}
      onClose={onClose}
      data-testid="scheduled-exports-modal"
      className="max-w-3xl"
    >
      <DialogHeader>
        <div className="flex items-center space-x-2">
          <Calendar className="h-5 w-5 text-indigo-600" />
          <DialogTitle>Scheduled Queue Reports</DialogTitle>
        </div>
        <DialogDescription>
          Automate regular queue export reports delivered directly to team email inboxes.
        </DialogDescription>
      </DialogHeader>

      <div className="space-y-6 py-3 max-h-[70vh] overflow-y-auto px-0.5">
        {/* Active Schedules List */}
        <div>
          <h3 className="text-sm font-semibold text-slate-900 mb-2 flex items-center justify-between">
            <span>Configured Schedules</span>
            <span className="text-xs font-normal text-slate-500">
              {schedules.length} {schedules.length === 1 ? 'schedule' : 'schedules'}
            </span>
          </h3>

          {isLoading ? (
            <div className="p-8 text-center text-slate-500 flex flex-col items-center justify-center space-y-2">
              <Loader2 className="h-6 w-6 animate-spin text-indigo-600" />
              <span className="text-xs">Loading schedules...</span>
            </div>
          ) : loadError ? (
            <div className="p-4 bg-rose-50 border border-rose-200 rounded-md text-xs text-rose-700 flex items-center space-x-2">
              <AlertCircle className="h-4 w-4 flex-shrink-0" />
              <span>{loadError}</span>
            </div>
          ) : (
            <div
              data-testid="schedule-list"
              className="space-y-2.5 divide-y divide-slate-100 rounded-lg border border-slate-200 bg-slate-50/50 p-2"
            >
              {schedules.length === 0 ? (
                <div className="p-6 text-center text-slate-500 text-xs">
                  No automated export schedules configured yet. Create one below to get started.
                </div>
              ) : (
                schedules.map((sch) => {
                  const id = sch.schedule_id || sch.scheduleId || ''
                  const feedback = triggerFeedback[id]

                  return (
                    <div
                      key={id}
                      className="pt-2.5 first:pt-0 bg-white rounded-md p-3 border border-slate-100 shadow-sm transition-all"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center space-x-2 flex-wrap gap-y-1">
                            <span className="text-sm font-semibold text-slate-900 truncate">
                              {sch.name}
                            </span>
                            <span
                              data-testid={`schedule-frequency-${id}`}
                              className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium bg-indigo-50 text-indigo-700 border border-indigo-100 capitalize"
                            >
                              <Clock className="h-3 w-3 mr-1" />
                              {sch.frequency}
                            </span>
                            <span
                              data-testid={`schedule-format-${id}`}
                              className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium bg-slate-100 text-slate-700 border border-slate-200 uppercase"
                            >
                              <FileSpreadsheet className="h-3 w-3 mr-1" />
                              {sch.format}
                            </span>
                          </div>

                          {/* Recipients list */}
                          <div className="mt-1 flex items-center text-xs text-slate-500">
                            <Mail className="h-3.5 w-3.5 mr-1.5 flex-shrink-0 text-slate-400" />
                            <span
                              data-testid={`schedule-recipients-${id}`}
                              className="truncate font-mono text-[11px]"
                            >
                              {Array.isArray(sch.recipients) ? sch.recipients.join(', ') : sch.recipients}
                            </span>
                          </div>

                          {/* Last run status info */}
                          <div className="mt-1 text-[11px] text-slate-400 flex items-center space-x-2">
                            <span>
                              Status:{' '}
                              <span
                                className={cn(
                                  'font-medium capitalize',
                                  sch.last_status === 'success' && 'text-emerald-600',
                                  sch.last_status === 'failure' && 'text-rose-600',
                                  (!sch.last_status || sch.last_status === 'never_run') && 'text-slate-400'
                                )}
                              >
                                {sch.last_status ? sch.last_status.replace('_', ' ') : 'never run'}
                              </span>
                            </span>
                            {sch.last_run && (
                              <span>• Last run: {new Date(sch.last_run).toLocaleString()}</span>
                            )}
                          </div>
                        </div>

                        {/* Controls */}
                        <div className="flex items-center space-x-2 flex-shrink-0">
                          {/* Enabled Toggle */}
                          <label className="flex items-center space-x-1.5 text-xs text-slate-600 cursor-pointer select-none">
                            <input
                              type="checkbox"
                              role="switch"
                              data-testid={`schedule-enabled-${id}`}
                              checked={sch.enabled}
                              onChange={() => handleToggleEnabled(sch)}
                              className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500 cursor-pointer"
                            />
                            <span className="text-[11px] font-medium">
                              {sch.enabled ? 'Active' : 'Paused'}
                            </span>
                          </label>

                          {/* Run Now Button */}
                          <Button
                            type="button"
                            size="sm"
                            variant="secondary"
                            data-testid={`schedule-trigger-${id}`}
                            disabled={triggeringId === id}
                            onClick={() => handleTrigger(sch)}
                            className="h-7 text-xs px-2.5"
                          >
                            {triggeringId === id ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin mr-1 text-slate-600" />
                            ) : (
                              <Play className="h-3 w-3 mr-1 text-emerald-600 fill-emerald-600" />
                            )}
                            Run Now
                          </Button>

                          {/* Delete Button */}
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            data-testid={`schedule-delete-${id}`}
                            disabled={deletingId === id}
                            onClick={() => handleDelete(sch)}
                            className="h-7 text-xs px-2 text-rose-600 hover:text-rose-700 hover:bg-rose-50"
                          >
                            {deletingId === id ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            ) : (
                              <Trash2 className="h-3.5 w-3.5" />
                            )}
                          </Button>
                        </div>
                      </div>

                      {/* Trigger result feedback */}
                      {feedback && (
                        <div
                          className={cn(
                            'mt-2 p-2 rounded text-xs flex items-center space-x-1.5',
                            feedback.type === 'success'
                              ? 'bg-emerald-50 text-emerald-800 border border-emerald-200'
                              : 'bg-rose-50 text-rose-800 border border-rose-200'
                          )}
                        >
                          {feedback.type === 'success' ? (
                            <CheckCircle className="h-3.5 w-3.5 text-emerald-600 flex-shrink-0" />
                          ) : (
                            <AlertCircle className="h-3.5 w-3.5 text-rose-600 flex-shrink-0" />
                          )}
                          <span>{feedback.message}</span>
                        </div>
                      )}
                    </div>
                  )
                })
              )}
            </div>
          )}
        </div>

        {/* Create Schedule Form */}
        <div className="border-t border-slate-200 pt-4">
          <h3 className="text-sm font-semibold text-slate-900 mb-3 flex items-center">
            <Plus className="h-4 w-4 mr-1.5 text-indigo-600" />
            Create New Export Schedule
          </h3>

          <form
            data-testid="create-schedule-form"
            onSubmit={handleCreate}
            className="space-y-3 bg-slate-50 p-4 rounded-lg border border-slate-200"
          >
            {formError && (
              <div className="p-2.5 bg-rose-50 border border-rose-200 rounded text-xs text-rose-700 flex items-center space-x-1.5">
                <AlertCircle className="h-4 w-4 flex-shrink-0" />
                <span>{formError}</span>
              </div>
            )}

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">
                  Schedule Name <span className="text-rose-500">*</span>
                </label>
                <input
                  type="text"
                  data-testid="schedule-name-input"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Daily Queue Audit"
                  className="w-full text-xs px-3 py-1.5 rounded-md border border-slate-300 focus:outline-none focus:ring-1 focus:ring-indigo-500 bg-white"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">
                  Recipients (comma-separated) <span className="text-rose-500">*</span>
                </label>
                <input
                  type="text"
                  data-testid="schedule-recipients-input"
                  value={recipientsText}
                  onChange={(e) => setRecipientsText(e.target.value)}
                  placeholder="manager@example.com, audit@example.com"
                  className="w-full text-xs px-3 py-1.5 rounded-md border border-slate-300 focus:outline-none focus:ring-1 focus:ring-indigo-500 bg-white"
                />
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">
                  Frequency
                </label>
                <select
                  data-testid="schedule-frequency-select"
                  value={frequency}
                  onChange={(e) => setFrequency(e.target.value as 'daily' | 'weekly')}
                  className="w-full text-xs px-3 py-1.5 rounded-md border border-slate-300 focus:outline-none focus:ring-1 focus:ring-indigo-500 bg-white"
                >
                  <option value="daily">Daily</option>
                  <option value="weekly">Weekly</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">
                  Format
                </label>
                <select
                  data-testid="schedule-format-select"
                  value={format}
                  onChange={(e) => setFormat(e.target.value as 'csv' | 'json')}
                  className="w-full text-xs px-3 py-1.5 rounded-md border border-slate-300 focus:outline-none focus:ring-1 focus:ring-indigo-500 bg-white"
                >
                  <option value="csv">CSV (Comma-Separated)</option>
                  <option value="json">JSON (Structured)</option>
                </select>
              </div>
            </div>

            <div className="pt-2 flex justify-end">
              <Button
                type="submit"
                size="sm"
                data-testid="create-schedule-submit"
                disabled={isSubmitting}
                className="bg-indigo-600 hover:bg-indigo-700 text-white"
              >
                {isSubmitting ? (
                  <>
                    <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" />
                    Creating...
                  </>
                ) : (
                  <>
                    <Plus className="h-3.5 w-3.5 mr-1" />
                    Create Schedule
                  </>
                )}
              </Button>
            </div>
          </form>
        </div>
      </div>

      <DialogFooter>
        <Button type="button" variant="secondary" onClick={onClose}>
          Close
        </Button>
      </DialogFooter>
    </Dialog>
  )
}
