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

describe('Detail Inspection Drawer Integration Tests', () => {
  it('opens detail drawer on Review / Inspect click, displaying Customer Intake, Classifier confidence, Policy rules, Decision reasoning, and email drafts', async () => {
    renderApp()

    // Wait for records to appear in queue
    await waitFor(() => {
      expect(screen.getByText('ORD-1001')).toBeInTheDocument()
    })

    // Click Review / Inspect for ORD-1001
    const inspectBtn = screen.getByRole('button', { name: /review order ord-1001/i })
    fireEvent.click(inspectBtn)

    // Verify RefundDetailDrawer opens and loads record details
    await waitFor(() => {
      const dialog = screen.getByRole('dialog')
      expect(within(dialog).getByText(/Customer Request & Order Intake/i)).toBeInTheDocument()
    })
    const dialog = screen.getByRole('dialog')
    const { getByText, getByRole } = within(dialog)

    // Customer Intake text
    expect(
      getByText(/The ceramic vase arrived shattered inside shipping box with no padding/i)
    ).toBeInTheDocument()

    // Classifier Confidence & Category
    expect(getByText(/Classification & Confidence/i)).toBeInTheDocument()
    expect(getByText(/96%/i)).toBeInTheDocument()
    expect(getByText(/^damaged$/i)).toBeInTheDocument()

    // Policy Checker Rule
    expect(getByText(/Policy Rule Validation/i)).toBeInTheDocument()
    expect(getByText(/standard_30_day_damaged/i)).toBeInTheDocument()

    // Decision Agent Reasoning
    expect(getByText(/Decision & Synthesized Reasoning/i)).toBeInTheDocument()
    expect(
      getByText(/Category damaged meets standard 30-day window policy. Auto-approved./i)
    ).toBeInTheDocument()

    // Email drafts
    const approvalBtn = getByRole('button', { name: /Approval Draft/i })
    expect(approvalBtn).toBeInTheDocument()
    expect(
      getByText(/Dear Customer, your refund request of \$85.50 has been approved./i)
    ).toBeInTheDocument()

    // Switch to Denial Email tab
    const denialBtn = getByRole('button', { name: /Denial Draft/i })
    fireEvent.click(denialBtn)
    expect(
      getByText(/No email generated for this workflow state/i)
    ).toBeInTheDocument()
  })
})
