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

describe('Refund Creation Integration Tests', () => {
  it('opens CreateRefundModal, submits new refund request, invalidates queue cache, and displays new record in table', async () => {
    renderApp()

    // Wait for initial queue load
    await waitFor(() => {
      expect(screen.getByText('ORD-1001')).toBeInTheDocument()
    })

    // Click "+ New Refund"
    const newRefundBtn = screen.getByTestId('new-refund-button')
    fireEvent.click(newRefundBtn)

    // Verify modal opened
    expect(screen.getByText('Submit Refund Request')).toBeInTheDocument()

    // Fill in Order ID
    const orderInput = screen.getByLabelText(/order id/i)
    fireEvent.change(orderInput, { target: { value: 'ORD-9001' } })

    // Fill in Customer Request Text
    const textarea = screen.getByLabelText(/customer request text/i)
    fireEvent.change(textarea, {
      target: { value: 'Customer states package arrived with torn seal and missing contents.' },
    })

    // Submit refund request
    const submitBtn = screen.getByRole('button', { name: /submit refund/i })
    fireEvent.click(submitBtn)

    // Modal closes and new order appears in queue table
    await waitFor(() => {
      expect(screen.queryByText('Submit Refund Request')).not.toBeInTheDocument()
      expect(screen.getByText('ORD-9001')).toBeInTheDocument()
    })
  })
})
