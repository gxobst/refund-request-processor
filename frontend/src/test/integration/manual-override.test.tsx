import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
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

describe('Manual Override Integration Tests', () => {
  it('opens ManualOverrideModal from drawer, approves refund with justification and confirmation guard, dispatches override, and refreshes queue', async () => {
    renderApp()

    // Wait for queue table to load
    await waitFor(() => {
      expect(screen.getByText('ORD-1002')).toBeInTheDocument()
    })

    // Click "Review / Inspect" for escalated order ORD-1002
    const inspectBtn = screen.getByRole('button', { name: /review order ord-1002/i })
    fireEvent.click(inspectBtn)

    // Wait for drawer to open
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /manual override/i })).toBeInTheDocument()
    })

    // Trigger manual override modal
    const overrideTriggerBtn = screen.getByRole('button', { name: /manual override/i })
    fireEvent.click(overrideTriggerBtn)

    // Verify modal is displayed
    await waitFor(() => {
      expect(screen.getByText('Manual Decision Override')).toBeInTheDocument()
      expect(screen.getAllByText('ORD-1002').length).toBeGreaterThan(0)
    })

    // Select "Approve Refund"
    const approveBtn = screen.getByRole('button', { name: /approve refund/i })
    fireEvent.click(approveBtn)

    // Enter mandatory justification
    const textarea = screen.getByLabelText(/override justification/i)
    fireEvent.change(textarea, {
      target: { value: 'Customer provided return tracking receipt showing carrier scan.' },
    })

    // Check confirmation guard checkbox
    const confirmCheckbox = screen.getByLabelText(/i confirm this manual decision override/i)
    fireEvent.click(confirmCheckbox)

    // Submit override
    const submitBtn = screen.getByRole('button', { name: /submit override/i })
    fireEvent.click(submitBtn)

    // Modal closes and queue table reflects the update
    await waitFor(() => {
      expect(screen.queryByText('Manual Decision Override')).not.toBeInTheDocument()
    })

    // Assert the decision and status for ORD-1002 have updated to "Manually Approved"
    await waitFor(() => {
      const orderCells = screen.getAllByText('ORD-1002')
      const row = orderCells.find((el) => el.closest('tr'))?.closest('tr')
      expect(row).toBeInTheDocument()
      expect(row).toHaveTextContent(/Completed/i)
      expect(row).toHaveTextContent(/Manually Approved/i)
    })
  })
})
