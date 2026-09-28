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
  return render(
    <QueryClientProvider client={testClient}>
      <App />
    </QueryClientProvider>
  )
}

describe('RFC 9457 ProblemDetails Error Handling Integration Tests', () => {
  it('renders accessible error banner on HTTP 500 queue error, and recovers when retry button is clicked', async () => {
    let failureCount = 1

    server.use(
      http.get('*/v1/refunds', () => {
        if (failureCount > 0) {
          failureCount--
          return HttpResponse.json(
            {
              type: 'urn:problem:internal-server-error',
              title: 'Internal Server Error',
              status: 500,
              detail: 'DynamoDB connection timed out while querying refund records.',
            },
            { status: 500, headers: { 'content-type': 'application/problem+json' } }
          )
        }
        return HttpResponse.json(mockRefunds)
      })
    )

    renderApp()

    // Assert accessible error banner is displayed
    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument()
      expect(screen.getByText('Internal Server Error')).toBeInTheDocument()
      expect(
        screen.getByText('DynamoDB connection timed out while querying refund records.')
      ).toBeInTheDocument()
    })

    // Click Retry
    const retryBtn = screen.getByRole('button', { name: /retry/i })
    fireEvent.click(retryBtn)

    // Assert recovery - records are displayed
    await waitFor(() => {
      expect(screen.getByText('ORD-1001')).toBeInTheDocument()
      expect(screen.queryByText('DynamoDB connection timed out while querying refund records.')).not.toBeInTheDocument()
    })
  })

  it('renders RFC 9457 error banner on HTTP 404 in detail drawer, and recovers on retry', async () => {
    let failureCount = 1

    server.use(
      http.get('*/v1/refunds/ref-101', () => {
        if (failureCount > 0) {
          failureCount--
          return HttpResponse.json(
            {
              type: 'https://api.refund-processor.local/problems/not-found',
              title: 'Refund Record Not Found',
              status: 404,
              detail: 'The requested refund evaluation record has been purged or moved.',
            },
            { status: 404, headers: { 'content-type': 'application/problem+json' } }
          )
        }
        return HttpResponse.json(mockRefunds[0])
      })
    )

    renderApp()

    await waitFor(() => {
      expect(screen.getByText('ORD-1001')).toBeInTheDocument()
    })

    const inspectBtn = screen.getByRole('button', { name: /review order ord-1001/i })
    fireEvent.click(inspectBtn)

    // Assert drawer error banner
    await waitFor(() => {
      expect(screen.getByTestId('detail-error-banner')).toBeInTheDocument()
      expect(screen.getByText('Refund Record Not Found')).toBeInTheDocument()
      expect(
        screen.getByText('The requested refund evaluation record has been purged or moved.')
      ).toBeInTheDocument()
    })

    // Click retry in drawer
    const retryBtn = screen.getByRole('button', { name: /retry/i })
    fireEvent.click(retryBtn)

    // Recovers successfully
    await waitFor(() => {
      expect(screen.getByText(/Customer Request & Order Intake/i)).toBeInTheDocument()
      expect(screen.queryByTestId('detail-error-banner')).not.toBeInTheDocument()
    })
  })
})
