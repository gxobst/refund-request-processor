import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/mocks/server'
import { mockRefunds } from '@/test/mocks/handlers'
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
  return {
    ...render(
      <QueryClientProvider client={testClient}>
        <App client={testClient} />
      </QueryClientProvider>
    ),
    client: testClient,
  }
}

describe('Queue Browsing, Filtering and Polling Integration Tests', () => {
  it('verifies clicking the "All" tab requests GET /v1/refunds without status query parameter, sets aria-selected="true", displays all 5 mock records, and displays active tab badge count 5', async () => {
    const requestedUrls: string[] = []
    server.use(
      http.get('*/v1/refunds', ({ request }) => {
        requestedUrls.push(request.url)
        const url = new URL(request.url)
        const statusFilter = url.searchParams.get('status')
        let results = [...mockRefunds]
        if (statusFilter) {
          results = results.filter((r) => r.status === statusFilter)
        }
        return HttpResponse.json(results)
      })
    )

    renderApp()

    // Wait for initial load
    await waitFor(() => {
      expect(screen.getByText('ORD-1001')).toBeInTheDocument()
    })

    // Click "Pending" tab first to leave "All"
    const pendingTab = screen.getByRole('tab', { name: /pending/i })
    fireEvent.click(pendingTab)

    await waitFor(() => {
      expect(screen.getByText('ORD-1004')).toBeInTheDocument()
      expect(screen.queryByText('ORD-1001')).not.toBeInTheDocument()
    })

    // Now click the "All" tab
    requestedUrls.length = 0
    const allTab = screen.getByRole('tab', { name: /^all/i })
    fireEvent.click(allTab)

    // Verify aria-selected="true" on "All" tab and "false" on others
    await waitFor(() => {
      expect(allTab).toHaveAttribute('aria-selected', 'true')
    })
    expect(screen.getByRole('tab', { name: /^pending/i })).toHaveAttribute('aria-selected', 'false')

    // Verify all 5 mock records are displayed
    await waitFor(() => {
      expect(screen.getByText('ORD-1001')).toBeInTheDocument()
      expect(screen.getByText('ORD-1002')).toBeInTheDocument()
      expect(screen.getByText('ORD-1003')).toBeInTheDocument()
      expect(screen.getByText('ORD-1004')).toBeInTheDocument()
      expect(screen.getByText('ORD-1005')).toBeInTheDocument()
    })

    const rows = screen.getAllByTestId('refund-row')
    expect(rows).toHaveLength(5)

    // Verify active tab badge count is 5
    const allBadge = screen.getByTestId('tab-count-all')
    expect(allBadge).toHaveTextContent('5')

    // Verify request was issued without status query parameter
    const allTabRequest = requestedUrls.find((rawUrl) => {
      const parsed = new URL(rawUrl)
      return parsed.pathname.endsWith('/v1/refunds') && !parsed.searchParams.has('status')
    })
    expect(allTabRequest).toBeDefined()
  })

  it('verifies clicking the "Pending" tab requests GET /v1/refunds?status=pending, sets aria-selected="true", displays only ORD-1004, displays active tab badge count 1, and displays active polling indicator text "Live - polling every 3s"', async () => {
    const requestedUrls: string[] = []
    server.use(
      http.get('*/v1/refunds', ({ request }) => {
        requestedUrls.push(request.url)
        const url = new URL(request.url)
        const statusFilter = url.searchParams.get('status')
        let results = [...mockRefunds]
        if (statusFilter) {
          results = results.filter((r) => r.status === statusFilter)
        }
        return HttpResponse.json(results)
      })
    )

    renderApp()

    await waitFor(() => {
      expect(screen.getByText('ORD-1001')).toBeInTheDocument()
    })

    const pendingTab = screen.getByRole('tab', { name: /pending/i })
    fireEvent.click(pendingTab)

    // Verify aria-selected="true"
    await waitFor(() => {
      expect(pendingTab).toHaveAttribute('aria-selected', 'true')
    })

    // Verify only ORD-1004 is displayed
    await waitFor(() => {
      expect(screen.getByText('ORD-1004')).toBeInTheDocument()
      expect(screen.queryByText('ORD-1001')).not.toBeInTheDocument()
      expect(screen.queryByText('ORD-1002')).not.toBeInTheDocument()
      expect(screen.queryByText('ORD-1003')).not.toBeInTheDocument()
      expect(screen.queryByText('ORD-1005')).not.toBeInTheDocument()
    })

    const rows = screen.getAllByTestId('refund-row')
    expect(rows).toHaveLength(1)

    // Verify active tab badge count is 1
    const pendingBadge = screen.getByTestId('tab-count-pending')
    expect(pendingBadge).toHaveTextContent('1')

    // Verify active polling indicator text "Live - polling every 3s"
    const pollingIndicator = screen.getByTestId('table-polling-indicator')
    expect(pollingIndicator).toHaveTextContent(/Live - polling every 3s/i)

    // Verify request issued with status=pending
    const pendingRequest = requestedUrls.find((rawUrl) => {
      const parsed = new URL(rawUrl)
      return (
        parsed.pathname.endsWith('/v1/refunds') &&
        parsed.searchParams.get('status') === 'pending'
      )
    })
    expect(pendingRequest).toBeDefined()
  })

  it('verifies clicking the "Completed" tab requests GET /v1/refunds?status=completed, sets aria-selected="true", displays only ORD-1001 and ORD-1005, displays active tab badge count 2, and displays idle polling indicator text "Idle"', async () => {
    const requestedUrls: string[] = []
    server.use(
      http.get('*/v1/refunds', ({ request }) => {
        requestedUrls.push(request.url)
        const url = new URL(request.url)
        const statusFilter = url.searchParams.get('status')
        let results = [...mockRefunds]
        if (statusFilter) {
          results = results.filter((r) => r.status === statusFilter)
        }
        return HttpResponse.json(results)
      })
    )

    renderApp()

    await waitFor(() => {
      expect(screen.getByText('ORD-1001')).toBeInTheDocument()
    })

    const completedTab = screen.getByRole('tab', { name: /completed/i })
    fireEvent.click(completedTab)

    // Verify aria-selected="true"
    await waitFor(() => {
      expect(completedTab).toHaveAttribute('aria-selected', 'true')
    })

    // Verify only ORD-1001 and ORD-1005 are displayed
    await waitFor(() => {
      expect(screen.getByText('ORD-1001')).toBeInTheDocument()
      expect(screen.getByText('ORD-1005')).toBeInTheDocument()
      expect(screen.queryByText('ORD-1002')).not.toBeInTheDocument()
      expect(screen.queryByText('ORD-1003')).not.toBeInTheDocument()
      expect(screen.queryByText('ORD-1004')).not.toBeInTheDocument()
    })

    const rows = screen.getAllByTestId('refund-row')
    expect(rows).toHaveLength(2)

    // Verify active tab badge count is 2
    const completedBadge = screen.getByTestId('tab-count-completed')
    expect(completedBadge).toHaveTextContent('2')

    // Verify idle polling indicator text "Idle"
    const pollingIndicator = screen.getByTestId('table-polling-indicator')
    expect(pollingIndicator).toHaveTextContent(/Idle/i)

    // Verify request issued with status=completed
    const completedRequest = requestedUrls.find((rawUrl) => {
      const parsed = new URL(rawUrl)
      return (
        parsed.pathname.endsWith('/v1/refunds') &&
        parsed.searchParams.get('status') === 'completed'
      )
    })
    expect(completedRequest).toBeDefined()
  })

  it('verifies clicking the "Escalated" tab requests GET /v1/refunds?status=escalated, sets aria-selected="true", displays only ORD-1002, displays active tab badge count 1, and displays idle polling indicator text "Idle"', async () => {
    const requestedUrls: string[] = []
    server.use(
      http.get('*/v1/refunds', ({ request }) => {
        requestedUrls.push(request.url)
        const url = new URL(request.url)
        const statusFilter = url.searchParams.get('status')
        let results = [...mockRefunds]
        if (statusFilter) {
          results = results.filter((r) => r.status === statusFilter)
        }
        return HttpResponse.json(results)
      })
    )

    renderApp()

    await waitFor(() => {
      expect(screen.getByText('ORD-1001')).toBeInTheDocument()
    })

    const escalatedTab = screen.getByRole('tab', { name: /escalated/i })
    fireEvent.click(escalatedTab)

    // Verify aria-selected="true"
    await waitFor(() => {
      expect(escalatedTab).toHaveAttribute('aria-selected', 'true')
    })

    // Verify only ORD-1002 is displayed
    await waitFor(() => {
      expect(screen.getByText('ORD-1002')).toBeInTheDocument()
      expect(screen.queryByText('ORD-1001')).not.toBeInTheDocument()
      expect(screen.queryByText('ORD-1003')).not.toBeInTheDocument()
      expect(screen.queryByText('ORD-1004')).not.toBeInTheDocument()
      expect(screen.queryByText('ORD-1005')).not.toBeInTheDocument()
    })

    const rows = screen.getAllByTestId('refund-row')
    expect(rows).toHaveLength(1)

    // Verify active tab badge count is 1
    const escalatedBadge = screen.getByTestId('tab-count-escalated')
    expect(escalatedBadge).toHaveTextContent('1')

    // Verify idle polling indicator text "Idle"
    const pollingIndicator = screen.getByTestId('table-polling-indicator')
    expect(pollingIndicator).toHaveTextContent(/Idle/i)

    // Verify request issued with status=escalated
    const escalatedRequest = requestedUrls.find((rawUrl) => {
      const parsed = new URL(rawUrl)
      return (
        parsed.pathname.endsWith('/v1/refunds') &&
        parsed.searchParams.get('status') === 'escalated'
      )
    })
    expect(escalatedRequest).toBeDefined()
  })

  it('verifies clicking the "Awaiting Clarification" tab requests GET /v1/refunds?status=awaiting_clarification, sets aria-selected="true", displays only ORD-1003, displays active tab badge count 1, and displays idle polling indicator text "Idle"', async () => {
    const requestedUrls: string[] = []
    server.use(
      http.get('*/v1/refunds', ({ request }) => {
        requestedUrls.push(request.url)
        const url = new URL(request.url)
        const statusFilter = url.searchParams.get('status')
        let results = [...mockRefunds]
        if (statusFilter) {
          results = results.filter((r) => r.status === statusFilter)
        }
        return HttpResponse.json(results)
      })
    )

    renderApp()

    await waitFor(() => {
      expect(screen.getByText('ORD-1001')).toBeInTheDocument()
    })

    const awaitingTab = screen.getByRole('tab', { name: /awaiting clarification/i })
    fireEvent.click(awaitingTab)

    // Verify aria-selected="true"
    await waitFor(() => {
      expect(awaitingTab).toHaveAttribute('aria-selected', 'true')
    })

    // Verify only ORD-1003 is displayed
    await waitFor(() => {
      expect(screen.getByText('ORD-1003')).toBeInTheDocument()
      expect(screen.queryByText('ORD-1001')).not.toBeInTheDocument()
      expect(screen.queryByText('ORD-1002')).not.toBeInTheDocument()
      expect(screen.queryByText('ORD-1004')).not.toBeInTheDocument()
      expect(screen.queryByText('ORD-1005')).not.toBeInTheDocument()
    })

    const rows = screen.getAllByTestId('refund-row')
    expect(rows).toHaveLength(1)

    // Verify active tab badge count is 1
    const awaitingBadge = screen.getByTestId('tab-count-awaiting_clarification')
    expect(awaitingBadge).toHaveTextContent('1')

    // Verify idle polling indicator text "Idle"
    const pollingIndicator = screen.getByTestId('table-polling-indicator')
    expect(pollingIndicator).toHaveTextContent(/Idle/i)

    // Verify request issued with status=awaiting_clarification
    const awaitingRequest = requestedUrls.find((rawUrl) => {
      const parsed = new URL(rawUrl)
      return (
        parsed.pathname.endsWith('/v1/refunds') &&
        parsed.searchParams.get('status') === 'awaiting_clarification'
      )
    })
    expect(awaitingRequest).toBeDefined()
  })

  it('strictly isolates records when switching between tabs, excluding records with other statuses', async () => {
    renderApp()

    // Initial All tab: all 5 records present
    await waitFor(() => {
      expect(screen.getAllByTestId('refund-row')).toHaveLength(5)
    })

    // 1. Switch to Completed tab
    const completedTab = screen.getByRole('tab', { name: /completed/i })
    fireEvent.click(completedTab)

    await waitFor(() => {
      const rows = screen.getAllByTestId('refund-row')
      expect(rows).toHaveLength(2)
      expect(screen.getByText('ORD-1001')).toBeInTheDocument()
      expect(screen.getByText('ORD-1005')).toBeInTheDocument()
      expect(screen.queryByText('ORD-1002')).not.toBeInTheDocument()
      expect(screen.queryByText('ORD-1003')).not.toBeInTheDocument()
      expect(screen.queryByText('ORD-1004')).not.toBeInTheDocument()
    })

    // 2. Switch to Escalated tab
    const escalatedTab = screen.getByRole('tab', { name: /escalated/i })
    fireEvent.click(escalatedTab)

    await waitFor(() => {
      const rows = screen.getAllByTestId('refund-row')
      expect(rows).toHaveLength(1)
      expect(screen.getByText('ORD-1002')).toBeInTheDocument()
      expect(screen.queryByText('ORD-1001')).not.toBeInTheDocument()
      expect(screen.queryByText('ORD-1003')).not.toBeInTheDocument()
      expect(screen.queryByText('ORD-1004')).not.toBeInTheDocument()
      expect(screen.queryByText('ORD-1005')).not.toBeInTheDocument()
    })

    // 3. Switch to Awaiting Clarification tab
    const awaitingTab = screen.getByRole('tab', { name: /awaiting clarification/i })
    fireEvent.click(awaitingTab)

    await waitFor(() => {
      const rows = screen.getAllByTestId('refund-row')
      expect(rows).toHaveLength(1)
      expect(screen.getByText('ORD-1003')).toBeInTheDocument()
      expect(screen.queryByText('ORD-1001')).not.toBeInTheDocument()
      expect(screen.queryByText('ORD-1002')).not.toBeInTheDocument()
      expect(screen.queryByText('ORD-1004')).not.toBeInTheDocument()
      expect(screen.queryByText('ORD-1005')).not.toBeInTheDocument()
    })

    // 4. Switch to Pending tab
    const pendingTab = screen.getByRole('tab', { name: /pending/i })
    fireEvent.click(pendingTab)

    await waitFor(() => {
      const rows = screen.getAllByTestId('refund-row')
      expect(rows).toHaveLength(1)
      expect(screen.getByText('ORD-1004')).toBeInTheDocument()
      expect(screen.queryByText('ORD-1001')).not.toBeInTheDocument()
      expect(screen.queryByText('ORD-1002')).not.toBeInTheDocument()
      expect(screen.queryByText('ORD-1003')).not.toBeInTheDocument()
      expect(screen.queryByText('ORD-1005')).not.toBeInTheDocument()
    })

    // 5. Switch back to All tab
    const allTab = screen.getByRole('tab', { name: /^all/i })
    fireEvent.click(allTab)

    await waitFor(() => {
      const rows = screen.getAllByTestId('refund-row')
      expect(rows).toHaveLength(5)
      expect(screen.getByText('ORD-1001')).toBeInTheDocument()
      expect(screen.getByText('ORD-1002')).toBeInTheDocument()
      expect(screen.getByText('ORD-1003')).toBeInTheDocument()
      expect(screen.getByText('ORD-1004')).toBeInTheDocument()
      expect(screen.getByText('ORD-1005')).toBeInTheDocument()
    })
  })

  it('verifies network requests using MSW request interception assert that switching to each tab issues GET /v1/refunds with the exact status parameter', async () => {
    const interceptedQueries: Array<{ path: string; status: string | null }> = []

    server.use(
      http.get('*/v1/refunds', ({ request }) => {
        const url = new URL(request.url)
        interceptedQueries.push({
          path: url.pathname,
          status: url.searchParams.get('status'),
        })
        const statusFilter = url.searchParams.get('status')
        let results = [...mockRefunds]
        if (statusFilter) {
          results = results.filter((r) => r.status === statusFilter)
        }
        return HttpResponse.json(results)
      })
    )

    renderApp()

    await waitFor(() => {
      expect(screen.getByText('ORD-1001')).toBeInTheDocument()
    })

    // Tab sequence to test: Pending -> Completed -> Escalated -> Awaiting Clarification -> All
    const tabSequence = [
      { name: /pending/i, expectedStatus: 'pending', expectedOrder: 'ORD-1004' },
      { name: /completed/i, expectedStatus: 'completed', expectedOrder: 'ORD-1001' },
      { name: /escalated/i, expectedStatus: 'escalated', expectedOrder: 'ORD-1002' },
      { name: /awaiting clarification/i, expectedStatus: 'awaiting_clarification', expectedOrder: 'ORD-1003' },
      { name: /^all/i, expectedStatus: null, expectedOrder: 'ORD-1001' },
    ]

    for (const step of tabSequence) {
      const tabButton = screen.getByRole('tab', { name: step.name })
      interceptedQueries.length = 0
      fireEvent.click(tabButton)

      await waitFor(() => {
        expect(screen.getByText(step.expectedOrder)).toBeInTheDocument()
      })

      const matchedRequest = interceptedQueries.find(
        (q) => q.path.endsWith('/v1/refunds') && q.status === step.expectedStatus
      )
      expect(matchedRequest).toBeDefined()
      expect(matchedRequest?.status).toBe(step.expectedStatus)
    }
  })

  it('renders empty state container with text "No refund requests found in this view", badge count 0, and no error banner when status filter returns []', async () => {
    server.use(
      http.get('*/v1/refunds', ({ request }) => {
        const url = new URL(request.url)
        const statusFilter = url.searchParams.get('status')
        if (statusFilter === 'pending') {
          return HttpResponse.json([])
        }
        let results = [...mockRefunds]
        if (statusFilter) {
          results = results.filter((r) => r.status === statusFilter)
        }
        return HttpResponse.json(results)
      })
    )

    renderApp()

    // Wait for initial load
    await waitFor(() => {
      expect(screen.getByText('ORD-1001')).toBeInTheDocument()
    })

    // Click Pending tab (which returns empty list)
    const pendingTab = screen.getByRole('tab', { name: /pending/i })
    fireEvent.click(pendingTab)

    // Verify empty state container and message
    await waitFor(() => {
      expect(screen.getByTestId('empty-state')).toBeInTheDocument()
      expect(
        screen.getByText('No refund requests found in this view')
      ).toBeInTheDocument()
    })

    // Verify active tab badge count is 0
    const pendingBadge = screen.getByTestId('tab-count-pending')
    expect(pendingBadge).toHaveTextContent('0')

    // Verify no error banner is displayed
    expect(screen.queryByTestId('queue-error-banner')).not.toBeInTheDocument()

    // Verify no rows rendered
    expect(screen.queryAllByTestId('refund-row')).toHaveLength(0)
  })

  it('displays error alert banner data-testid="queue-error-banner" with RFC 9457 ProblemDetails when switching tabs fails with HTTP 500, and refetches active tab records on Retry', async () => {
    let failPending = true

    server.use(
      http.get('*/v1/refunds', ({ request }) => {
        const url = new URL(request.url)
        const statusFilter = url.searchParams.get('status')

        if (statusFilter === 'pending' && failPending) {
          return HttpResponse.json(
            {
              type: 'https://api.refund-processor.local/problems/internal-server-error',
              title: 'Storage Outage',
              status: 500,
              detail: 'DynamoDB connection failed during pending queue partition query.',
            },
            {
              status: 500,
              headers: { 'content-type': 'application/problem+json' },
            }
          )
        }

        let results = [...mockRefunds]
        if (statusFilter) {
          results = results.filter((r) => r.status === statusFilter)
        }
        return HttpResponse.json(results)
      })
    )

    renderApp()

    // Wait for initial records
    await waitFor(() => {
      expect(screen.getByText('ORD-1001')).toBeInTheDocument()
    })

    // Click Pending tab
    const pendingTab = screen.getByRole('tab', { name: /pending/i })
    fireEvent.click(pendingTab)

    // Verify error alert banner displays ProblemDetails
    await waitFor(() => {
      expect(screen.getByTestId('queue-error-banner')).toBeInTheDocument()
      expect(screen.getByText('Storage Outage')).toBeInTheDocument()
      expect(
        screen.getByText('DynamoDB connection failed during pending queue partition query.')
      ).toBeInTheDocument()
    })

    // Ensure error recovery: fix backend failure, click Retry button
    failPending = false
    const retryButton = screen.getByRole('button', { name: /retry/i })
    fireEvent.click(retryButton)

    // Verify recovery for active "pending" tab
    await waitFor(() => {
      expect(screen.getByText('ORD-1004')).toBeInTheDocument()
      expect(screen.queryByTestId('queue-error-banner')).not.toBeInTheDocument()
    })

    expect(screen.getByTestId('tab-count-pending')).toHaveTextContent('1')
    expect(screen.getByTestId('table-polling-indicator')).toHaveTextContent(
      /Live - polling every 3s/i
    )
  })
})
