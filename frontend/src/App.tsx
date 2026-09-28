import * as React from 'react'
import {
  QueryClient,
  QueryClientProvider,
  QueryClientContext,
  useQuery,
} from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { listRefunds, getRefundById } from '@/services/refundService'
import { AppLayout } from '@/components/layout/AppLayout'
import { RefundQueueTable } from '@/components/queue/RefundQueueTable'
import { RefundDetailDrawer } from '@/components/detail/RefundDetailDrawer'
import { EvidenceGallery } from '@/components/evidence/EvidenceGallery'
import { ClarificationHistoryViewer } from '@/components/clarification/ClarificationHistoryViewer'
import { ToolExecutionAuditViewer } from '@/components/audit/ToolExecutionAuditViewer'
import {
  CreateRefundModal,
  ManualOverrideModal,
  RequestProofModal,
} from '@/components/modals'
import { Button } from '@/components/ui/Button'
import type { RefundRecord } from '@/types/api'

const defaultQueryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
})

function AppContent() {
  const [selectedRefundId, setSelectedRefundId] = React.useState<string | null>(null)
  const [isDrawerOpen, setIsDrawerOpen] = React.useState(false)
  const [isCreateModalOpen, setIsCreateModalOpen] = React.useState(false)
  const [isOverrideModalOpen, setIsOverrideModalOpen] = React.useState(false)
  const [isRequestProofModalOpen, setIsRequestProofModalOpen] = React.useState(false)

  // Fetch all refunds to determine polling state (if any pending)
  const { data: allRefunds = [] } = useQuery<RefundRecord[]>({
    queryKey: ['refunds', 'all-for-polling'],
    queryFn: () => listRefunds(),
    refetchInterval: (query) => {
      const data = query.state.data
      const hasPending = data?.some((r) => r.status === 'pending')
      return hasPending ? 3000 : false
    },
  })

  const isPolling = React.useMemo(() => {
    return allRefunds.some((r) => r.status === 'pending')
  }, [allRefunds])

  // Fetch selected refund detail for children extension slots and modals
  const { data: selectedRefund } = useQuery<RefundRecord>({
    queryKey: ['refund', selectedRefundId],
    queryFn: () => getRefundById(selectedRefundId!),
    enabled: Boolean(selectedRefundId),
  })

  const handleSelectRefund = (refundId: string) => {
    setSelectedRefundId(refundId)
    setIsDrawerOpen(true)
  }

  const handleCloseDrawer = () => {
    setIsDrawerOpen(false)
  }

  const handleTriggerOverride = (refundId: string) => {
    setSelectedRefundId(refundId)
    setIsOverrideModalOpen(true)
  }

  const handleTriggerRequestProof = (refundId: string) => {
    setSelectedRefundId(refundId)
    setIsRequestProofModalOpen(true)
  }

  return (
    <AppLayout
      headerProps={{
        systemHealth: 'operational',
        isPolling,
        pollingIntervalSeconds: 3,
      }}
    >
      <div className="space-y-6">
        {/* Header Action Bar */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <h2 className="text-xl font-semibold text-slate-900 tracking-tight">
              Back-Office Operations
            </h2>
            <p className="text-sm text-slate-500">
              Automated refund evaluation queue powered by multi-agent LangGraph workflow.
            </p>
          </div>
          <div>
            <Button
              variant="default"
              size="sm"
              onClick={() => setIsCreateModalOpen(true)}
              data-testid="new-refund-button"
              className="bg-slate-900 text-white hover:bg-slate-800"
            >
              <Plus className="h-4 w-4 mr-1.5" />
              + New Refund
            </Button>
          </div>
        </div>

        {/* Refund Queue Table */}
        <RefundQueueTable onSelectRefund={handleSelectRefund} />

        {/* Detail Inspection Drawer with extensions */}
        <RefundDetailDrawer
          refundId={selectedRefundId}
          isOpen={isDrawerOpen}
          onClose={handleCloseDrawer}
          onTriggerOverride={handleTriggerOverride}
          onTriggerRequestProof={handleTriggerRequestProof}
        >
          <EvidenceGallery evidence={selectedRefund?.evidence} />
          <ClarificationHistoryViewer history={selectedRefund?.clarificationHistory} />
          <ToolExecutionAuditViewer toolCalls={selectedRefund?.toolCalls} />
        </RefundDetailDrawer>

        {/* Modals */}
        <CreateRefundModal
          isOpen={isCreateModalOpen}
          onClose={() => setIsCreateModalOpen(false)}
        />

        <ManualOverrideModal
          refundId={selectedRefundId}
          orderId={selectedRefund?.orderId}
          currentDecision={selectedRefund?.decision}
          isOpen={isOverrideModalOpen}
          onClose={() => setIsOverrideModalOpen(false)}
        />

        <RequestProofModal
          refundId={selectedRefundId}
          orderId={selectedRefund?.orderId}
          isOpen={isRequestProofModalOpen}
          onClose={() => setIsRequestProofModalOpen(false)}
        />
      </div>
    </AppLayout>
  )
}

export interface AppProps {
  client?: QueryClient
}

export function App({ client }: AppProps) {
  const existingClient = React.useContext(QueryClientContext)

  if (!existingClient && !client) {
    return (
      <QueryClientProvider client={defaultQueryClient}>
        <AppContent />
      </QueryClientProvider>
    )
  }

  if (client) {
    return (
      <QueryClientProvider client={client}>
        <AppContent />
      </QueryClientProvider>
    )
  }

  return <AppContent />
}

export default App
