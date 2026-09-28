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

describe('Queue Browsing, Filtering and Polling Integration Tests', () => {
  it('renders queue records from MSW, displays badges, filters by status tabs, and indicates live polling', async () => {
    renderApp()

    // Assert records load into queue table
    await waitFor(() => {
      expect(screen.getByText('ORD-1001')).toBeInTheDocument()
      expect(screen.getByText('ORD-1002')).toBeInTheDocument()
      expect(screen.getByText('ORD-1003')).toBeInTheDocument()
      expect(screen.getByText('ORD-1004')).toBeInTheDocument()
      expect(screen.getByText('ORD-1005')).toBeInTheDocument()
    })

    // Assert decision badges and status badges are rendered
    expect(screen.getByText(/Auto Approved/i)).toBeInTheDocument()
    expect(screen.getAllByText(/Escalated/i).length).toBeGreaterThan(0)
    expect(screen.getByText(/Denied/i)).toBeInTheDocument()

    // Assert live polling indicator is active because ORD-1004 has status: 'pending'
    const pollingStatus = screen.getByTestId('polling-status')
    expect(pollingStatus).toHaveTextContent(/Live - polling every 3s/i)

    // Filter by 'Completed' tab
    const completedTab = screen.getByRole('tab', { name: /Completed/i })
    fireEvent.click(completedTab)

    await waitFor(() => {
      expect(screen.getByText('ORD-1001')).toBeInTheDocument()
      expect(screen.getByText('ORD-1005')).toBeInTheDocument()
      expect(screen.queryByText('ORD-1002')).not.toBeInTheDocument()
      expect(screen.queryByText('ORD-1004')).not.toBeInTheDocument()
    })

    // Filter by 'Escalated' tab
    const escalatedTab = screen.getByRole('tab', { name: /Escalated/i })
    fireEvent.click(escalatedTab)

    await waitFor(() => {
      expect(screen.getByText('ORD-1002')).toBeInTheDocument()
      expect(screen.queryByText('ORD-1001')).not.toBeInTheDocument()
    })

    // Filter by 'Awaiting Clarification' tab
    const awaitingTab = screen.getByRole('tab', { name: /Awaiting Clarification/i })
    fireEvent.click(awaitingTab)

    await waitFor(() => {
      expect(screen.getByText('ORD-1003')).toBeInTheDocument()
      expect(screen.queryByText('ORD-1002')).not.toBeInTheDocument()
    })

    // Filter by 'Pending' tab
    const pendingTab = screen.getByRole('tab', { name: /Pending/i })
    fireEvent.click(pendingTab)

    await waitFor(() => {
      expect(screen.getByText('ORD-1004')).toBeInTheDocument()
      expect(screen.queryByText('ORD-1001')).not.toBeInTheDocument()
    })

    // Switch back to 'All'
    const allTab = screen.getByRole('tab', { name: /All/i })
    fireEvent.click(allTab)

    await waitFor(() => {
      expect(screen.getByText('ORD-1001')).toBeInTheDocument()
      expect(screen.getByText('ORD-1004')).toBeInTheDocument()
    })
  })
})
