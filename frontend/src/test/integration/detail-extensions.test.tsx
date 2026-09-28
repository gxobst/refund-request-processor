import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from '@/App'

function renderApp() {
  const testClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
      },
    },
  })
  return render(
    <QueryClientProvider client={testClient}>
      <App />
    </QueryClientProvider>
  )
}

describe('Detail Drawer Extensions Integration Tests', () => {
  it('renders EvidenceGallery with zoom preview, ClarificationHistoryViewer with chronological turns, and ToolExecutionAuditViewer with JSON disclosures', async () => {
    renderApp()

    // Wait for queue table to load
    await waitFor(() => {
      expect(screen.getByText('ORD-1003')).toBeInTheDocument()
    })

    // Inspect ORD-1003 (which contains evidence, clarification turn, and tool audits)
    const inspectBtn = screen.getByRole('button', { name: /review order ord-1003/i })
    fireEvent.click(inspectBtn)

    // Wait for drawer content to load
    await waitFor(() => {
      const dialog = screen.getByRole('dialog')
      expect(within(dialog).getByText(/Customer Request & Order Intake/i)).toBeInTheDocument()
    })

    // 1. Evidence Gallery thumbnail verification
    await waitFor(() => {
      expect(screen.getByText('shipping_bag.jpg')).toBeInTheDocument()
    })

    // 2. Clarification History verification
    await waitFor(() => {
      expect(
        screen.getByText(/Please upload a photo of the exterior shipping box and packing slip\./i)
      ).toBeInTheDocument()
      expect(screen.getByText(/Awaiting customer response/i)).toBeInTheDocument()
    })

    // 3. Tool Execution Audit verification
    await waitFor(() => {
      expect(screen.getByText(/query_carrier_tracking/i)).toBeInTheDocument()
      expect(screen.getByText(/query_payment_transaction/i)).toBeInTheDocument()
    })

    // Expand Input Arguments disclosure on tool call
    const toggleInputBtn = screen.getAllByTestId('toggle-inputs-button')[0]
    fireEvent.click(toggleInputBtn)

    await waitFor(() => {
      const inputsContent = screen.getByTestId('inputs-content')
      expect(inputsContent).toHaveTextContent(/ORD-1003/i)
    })

    // 4. Click Evidence Gallery thumbnail to open zoom preview modal
    const zoomCard = screen.getByRole('button', { name: /view evidence shipping_bag\.jpg/i })
    expect(zoomCard).toBeInTheDocument()
    fireEvent.click(zoomCard)

    // Zoom preview modal opens
    await waitFor(() => {
      expect(screen.getByTestId('zoom-modal-image')).toBeInTheDocument()
    })
  })
})
