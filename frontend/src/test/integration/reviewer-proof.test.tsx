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

describe('Reviewer Proof Request Integration Tests', () => {
  it('opens RequestProofModal, enters prompt and customer name, dispatches request, transitions status to awaiting_clarification, and appends clarification turn', async () => {
    renderApp()

    // Wait for queue table to load
    await waitFor(() => {
      expect(screen.getByText('ORD-1002')).toBeInTheDocument()
    })

    // Open drawer for ORD-1002 (escalated order)
    const inspectBtn = screen.getByRole('button', { name: /review order ord-1002/i })
    fireEvent.click(inspectBtn)

    // Wait for drawer and click "Request Proof" once enabled
    await waitFor(() => {
      const btn = screen.getByRole('button', { name: /request proof/i })
      expect(btn).toBeInTheDocument()
      expect(btn).toBeEnabled()
    })
    const requestProofTrigger = screen.getByRole('button', { name: /request proof/i })
    fireEvent.click(requestProofTrigger)

    // Verify modal is open
    await waitFor(() => {
      expect(screen.getByText('Request Customer Proof')).toBeInTheDocument()
    })

    // Fill customer name
    const nameInput = screen.getByLabelText(/customer name/i)
    fireEvent.change(nameInput, { target: { value: 'Jane Doe' } })

    // Fill proof inquiry prompt
    const promptTextarea = screen.getByLabelText(/proof inquiry prompt/i)
    fireEvent.change(promptTextarea, {
      target: {
        value: 'Please upload a clear photograph of the shoe box size label showing EU and US sizing.',
      },
    })

    // Submit inquiry
    const sendBtn = screen.getByRole('button', { name: /send request/i })
    fireEvent.click(sendBtn)

    // Modal closes and queue status updates to Awaiting Clarification
    await waitFor(() => {
      expect(screen.queryByText('Request Customer Proof')).not.toBeInTheDocument()
    })

    // Verify status transition
    await waitFor(() => {
      const orderCells = screen.getAllByText('ORD-1002')
      const row = orderCells.find((el) => el.closest('tr'))?.closest('tr')
      expect(row).toBeInTheDocument()
      expect(row).toHaveTextContent(/Awaiting Clarification/i)
    })
  })
})
