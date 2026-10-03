import * as React from 'react'
import {
  ArrowDown,
  ArrowUp,
  CheckSquare,
  Download,
  Square,
  SlidersHorizontal,
  X,
  AlertCircle,
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
import type { RefundRecord } from '@/types/api'
import {
  EXPORT_COLUMNS,
  serializeToCsv,
  serializeToJson,
  generateExportFilename,
  downloadExportFile,
} from '@/utils/exportUtils'

export interface ExportCustomizationModalProps {
  isOpen: boolean
  onClose: () => void
  records: RefundRecord[]
  statusFilter?: string
}

export const PRESET_OPTIONS = {
  default: {
    label: 'Default (All Columns)',
    columns: EXPORT_COLUMNS.map((c) => c.id),
  },
  accounting: {
    label: 'Accounting',
    columns: [
      'refund_id',
      'order_id',
      'refund_amount',
      'status',
      'decision',
      'created_at',
    ],
  },
  carrier_audit: {
    label: 'Carrier Audit',
    columns: [
      'refund_id',
      'order_id',
      'category',
      'status',
      'reasoning',
      'created_at',
    ],
  },
} as const

export const LOCAL_STORAGE_KEY = 'custom_export_columns'

function loadInitialConfig(): { order: string[]; selected: string[] } {
  const allIds = EXPORT_COLUMNS.map((c) => c.id)
  try {
    const raw = localStorage.getItem(LOCAL_STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw)
      if (Array.isArray(parsed)) {
        if (
          parsed.length > 0 &&
          typeof parsed[0] === 'object' &&
          parsed[0] !== null &&
          'id' in parsed[0]
        ) {
          const order = parsed
            .map((item: { id: string }) => item.id)
            .filter((id) => allIds.includes(id))
          const selected = parsed
            .filter((item: { selected?: boolean }) => item.selected)
            .map((item: { id: string }) => item.id)
            .filter((id) => allIds.includes(id))
          // Append any missing IDs
          const fullOrder = [...order, ...allIds.filter((id) => !order.includes(id))]
          return { order: fullOrder, selected }
        }
        const stringList = (parsed as string[]).filter((id) => allIds.includes(id))
        const fullOrder = [
          ...stringList,
          ...allIds.filter((id) => !stringList.includes(id)),
        ]
        return { order: fullOrder, selected: stringList }
      }
      if (parsed && typeof parsed === 'object') {
        const orderPart = (parsed.order || parsed.columnOrder || allIds) as string[]
        const validOrder = orderPart.filter((id) => allIds.includes(id))
        const fullOrder = [
          ...validOrder,
          ...allIds.filter((id) => !validOrder.includes(id)),
        ]
        const selectedPart = (parsed.selected ||
          parsed.selectedColumns ||
          validOrder) as string[]
        const validSelected = selectedPart.filter((id) => allIds.includes(id))
        return { order: fullOrder, selected: validSelected }
      }
    }
  } catch {
    // Ignore localStorage parse errors
  }
  return { order: allIds, selected: allIds }
}

function persistConfig(order: string[], selected: string[]): void {
  try {
    localStorage.setItem(LOCAL_STORAGE_KEY, JSON.stringify({ order, selected }))
  } catch {
    // Ignore localStorage write errors
  }
}

export function ExportCustomizationModal({
  isOpen,
  onClose,
  records,
  statusFilter,
}: ExportCustomizationModalProps) {
  const [orderedColumns, setOrderedColumns] = React.useState<string[]>(() => {
    return loadInitialConfig().order
  })
  const [selectedColumns, setSelectedColumns] = React.useState<string[]>(() => {
    return loadInitialConfig().selected
  })
  const [activePreset, setActivePreset] = React.useState<string>('default')

  // Re-read localStorage whenever modal opens
  React.useEffect(() => {
    if (isOpen) {
      const config = loadInitialConfig()
      setOrderedColumns(config.order)
      setSelectedColumns(config.selected)
    }
  }, [isOpen])

  // Sync state changes to localStorage
  const updateColumnsState = (nextOrder: string[], nextSelected: string[]) => {
    setOrderedColumns(nextOrder)
    setSelectedColumns(nextSelected)
    persistConfig(nextOrder, nextSelected)
  }

  const handleToggleColumn = (colId: string) => {
    const nextSelected = selectedColumns.includes(colId)
      ? selectedColumns.filter((id) => id !== colId)
      : [...selectedColumns, colId]
    setActivePreset('custom')
    setSelectedColumns(nextSelected)
    persistConfig(orderedColumns, nextSelected)
  }

  const handleSelectAll = () => {
    const all = [...orderedColumns]
    setSelectedColumns(all)
    setActivePreset('default')
    persistConfig(orderedColumns, all)
  }

  const handleDeselectAll = () => {
    setSelectedColumns([])
    setActivePreset('custom')
    persistConfig(orderedColumns, [])
  }

  const handleMoveUp = (index: number) => {
    if (index <= 0) return
    const next = [...orderedColumns]
    const temp = next[index]
    next[index] = next[index - 1]
    next[index - 1] = temp
    setActivePreset('custom')
    setOrderedColumns(next)
    persistConfig(next, selectedColumns)
  }

  const handleMoveDown = (index: number) => {
    if (index >= orderedColumns.length - 1) return
    const next = [...orderedColumns]
    const temp = next[index]
    next[index] = next[index + 1]
    next[index + 1] = temp
    setActivePreset('custom')
    setOrderedColumns(next)
    persistConfig(next, selectedColumns)
  }

  const handlePresetChange = (presetKey: string) => {
    setActivePreset(presetKey)
    const allIds = EXPORT_COLUMNS.map((c) => c.id)

    if (presetKey === 'default') {
      const nextOrder = [...allIds]
      const nextSelected = [...allIds]
      updateColumnsState(nextOrder, nextSelected)
    } else if (presetKey === 'accounting') {
      const presetCols = [...PRESET_OPTIONS.accounting.columns]
      const rest = allIds.filter((id) => !presetCols.includes(id as any))
      const nextOrder = [...presetCols, ...rest]
      updateColumnsState(nextOrder, presetCols)
    } else if (presetKey === 'carrier_audit') {
      const presetCols = [...PRESET_OPTIONS.carrier_audit.columns]
      const rest = allIds.filter((id) => !presetCols.includes(id as any))
      const nextOrder = [...presetCols, ...rest]
      updateColumnsState(nextOrder, presetCols)
    }
  }

  const activeColumnsInOrder = orderedColumns.filter((id) => selectedColumns.includes(id))
  const isExportDisabled = activeColumnsInOrder.length === 0

  const handleExportCsv = () => {
    if (isExportDisabled) return
    const filename = generateExportFilename('csv', statusFilter)
    const content = serializeToCsv(records, activeColumnsInOrder)
    downloadExportFile(content, filename, 'text/csv; charset=utf-8')
    persistConfig(orderedColumns, selectedColumns)
    onClose()
  }

  const handleExportJson = () => {
    if (isExportDisabled) return
    const filename = generateExportFilename('json', statusFilter)
    const content = serializeToJson(records, activeColumnsInOrder)
    downloadExportFile(content, filename, 'application/json')
    persistConfig(orderedColumns, selectedColumns)
    onClose()
  }

  return (
    <Dialog
      isOpen={isOpen}
      onClose={onClose}
      data-testid="export-customization-modal"
      aria-labelledby="export-customization-dialog-title"
      aria-describedby="export-customization-dialog-description"
      className="max-w-lg"
    >
      <div className="space-y-4">
        <DialogHeader>
          <div className="flex items-center space-x-2">
            <SlidersHorizontal className="h-5 w-5 text-slate-700" />
            <DialogTitle id="export-customization-dialog-title">
              Customize Queue Export
            </DialogTitle>
          </div>
          <DialogDescription id="export-customization-dialog-description">
            Select, reorder, and configure export columns for CSV and JSON downloads.
          </DialogDescription>
        </DialogHeader>

        {/* Presets and bulk controls */}
        <div className="space-y-3 pt-1">
          <div className="flex items-center justify-between gap-3">
            <label
              htmlFor="export-preset-select"
              className="text-xs font-semibold text-slate-700 flex-shrink-0"
            >
              Export Preset:
            </label>
            <select
              id="export-preset-select"
              data-testid="export-preset-select"
              value={activePreset}
              onChange={(e) => handlePresetChange(e.target.value)}
              className="w-full text-xs rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-slate-800 shadow-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
            >
              <option value="default">{PRESET_OPTIONS.default.label}</option>
              <option value="accounting">{PRESET_OPTIONS.accounting.label}</option>
              <option value="carrier_audit">{PRESET_OPTIONS.carrier_audit.label}</option>
              {activePreset === 'custom' && <option value="custom">Custom</option>}
            </select>
          </div>

          <div className="flex items-center justify-between text-xs pt-1 border-t border-slate-100">
            <span className="text-slate-500">
              {activeColumnsInOrder.length} of {orderedColumns.length} columns selected
            </span>
            <div className="flex items-center space-x-2">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                data-testid="column-select-all"
                onClick={handleSelectAll}
                className="h-7 px-2 text-xs text-slate-600 hover:text-slate-900"
              >
                <CheckSquare className="h-3.5 w-3.5 mr-1" />
                Select All
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                data-testid="column-deselect-all"
                onClick={handleDeselectAll}
                className="h-7 px-2 text-xs text-slate-600 hover:text-slate-900"
              >
                <Square className="h-3.5 w-3.5 mr-1" />
                Deselect All
              </Button>
            </div>
          </div>
        </div>

        {/* Column List with reordering and checkboxes */}
        <div
          data-testid="column-list"
          className="max-h-64 overflow-y-auto divide-y divide-slate-100 rounded-md border border-slate-200 bg-slate-50/50 p-1"
        >
          {orderedColumns.map((colId, index) => {
            const def = EXPORT_COLUMNS.find((c) => c.id === colId)
            const label = def?.label || colId
            const isChecked = selectedColumns.includes(colId)

            return (
              <div
                key={colId}
                className={cn(
                  'flex items-center justify-between px-2.5 py-1.5 text-xs transition-colors rounded',
                  isChecked ? 'bg-white text-slate-900' : 'text-slate-400 bg-transparent'
                )}
              >
                <label className="flex items-center space-x-2.5 cursor-pointer flex-1 select-none">
                  <input
                    type="checkbox"
                    data-testid={`column-checkbox-${colId}`}
                    checked={isChecked}
                    onChange={() => handleToggleColumn(colId)}
                    className="h-4 w-4 rounded border-slate-300 text-slate-900 focus:ring-slate-500"
                  />
                  <span className={cn('font-medium', isChecked ? 'text-slate-800' : 'text-slate-400')}>
                    {label}
                  </span>
                </label>

                {/* Reordering Up/Down controls */}
                <div className="flex items-center space-x-1 ml-2">
                  <button
                    type="button"
                    data-testid={`column-move-up-${colId}`}
                    disabled={index === 0}
                    onClick={() => handleMoveUp(index)}
                    aria-label={`Move ${label} up`}
                    className="p-1 rounded text-slate-400 hover:text-slate-700 hover:bg-slate-100 disabled:opacity-30 disabled:pointer-events-none"
                  >
                    <ArrowUp className="h-3.5 w-3.5" />
                  </button>
                  <button
                    type="button"
                    data-testid={`column-move-down-${colId}`}
                    disabled={index === orderedColumns.length - 1}
                    onClick={() => handleMoveDown(index)}
                    aria-label={`Move ${label} down`}
                    className="p-1 rounded text-slate-400 hover:text-slate-700 hover:bg-slate-100 disabled:opacity-30 disabled:pointer-events-none"
                  >
                    <ArrowDown className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            )
          })}
        </div>

        {/* Validation message if 0 columns selected */}
        {isExportDisabled && (
          <div
            data-testid="column-validation-error"
            role="alert"
            className="flex items-center space-x-2 rounded-md bg-rose-50 border border-rose-200 px-3 py-2 text-xs text-rose-700"
          >
            <AlertCircle className="h-4 w-4 text-rose-600 flex-shrink-0" />
            <span>At least one column must be selected</span>
          </div>
        )}

        {/* Footer actions */}
        <DialogFooter className="mt-4 sm:justify-between flex-wrap gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={onClose}
            className="h-8 px-3 text-xs"
          >
            Cancel
          </Button>

          <div className="flex items-center space-x-2 ml-auto">
            <Button
              type="button"
              variant="default"
              data-testid="modal-export-csv"
              disabled={isExportDisabled}
              onClick={handleExportCsv}
              className="h-8 px-3 text-xs bg-slate-900 text-white hover:bg-slate-800 disabled:opacity-50"
            >
              <Download className="h-3.5 w-3.5 mr-1.5" />
              Export CSV
            </Button>
            <Button
              type="button"
              variant="outline"
              data-testid="modal-export-json"
              disabled={isExportDisabled}
              onClick={handleExportJson}
              className="h-8 px-3 text-xs border-slate-300 text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            >
              <Download className="h-3.5 w-3.5 mr-1.5" />
              Export JSON
            </Button>
          </div>
        </DialogFooter>
      </div>
    </Dialog>
  )
}
