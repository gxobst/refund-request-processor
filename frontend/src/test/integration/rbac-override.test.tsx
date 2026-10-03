import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/mocks/server'
import { RoleProvider } from '@/context/RoleContext'
import App from '@/App'

function renderApp(initialRole?: 'agent' | 'supervisor') {
  const testClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
      },
      mutations: {
        retry: false,
      },
    },
  })

  return render(
    <QueryClientProvider client={testClient}>
      <RoleProvider initialRole={initialRole}>
        <App client={testClient} />
      </RoleProvider>
    </QueryClientProvider>
  )
}

describe('RBAC Role Switcher and Override Integration Tests', () => {
  beforeEach(() => {
    window.localStorage.clear()
  })

  it('renders Header role switcher with default Supervisor role and toggles between Supervisor, Senior Manager, and Agent', async () => {
    renderApp()

    // 1. Initial state: role switcher should be present and show Supervisor
    const roleSwitcher = await screen.findByTestId('role-switcher')
    expect(roleSwitcher).toBeInTheDocument()
    expect(roleSwitcher).toHaveTextContent('Supervisor')

    // 2. Toggle to Senior Manager
    fireEvent.click(roleSwitcher)
    expect(roleSwitcher).toHaveTextContent('Senior Manager')
    expect(window.localStorage.getItem('user_role')).toBe('senior_manager')

    // 3. Toggle to Agent
    fireEvent.click(roleSwitcher)
    expect(roleSwitcher).toHaveTextContent('Agent')
    expect(window.localStorage.getItem('user_role')).toBe('agent')

    // 4. Toggle back to Supervisor
    fireEvent.click(roleSwitcher)
    expect(roleSwitcher).toHaveTextContent('Supervisor')
    expect(window.localStorage.getItem('user_role')).toBe('supervisor')
  })

  it('disables Manual Override button with Lock icon and tooltip when active role is Agent', async () => {
    // Render directly in Agent mode
    renderApp('agent')

    // Wait for queue to populate
    await waitFor(() => {
      expect(screen.getByText('ORD-1002')).toBeInTheDocument()
    })

    // Open detail drawer for order ORD-1002
    const inspectBtn = screen.getByRole('button', { name: /review order ord-1002/i })
    fireEvent.click(inspectBtn)

    // Verify disabled override button is rendered with lock and tooltip
    await waitFor(() => {
      const disabledBtn = screen.getByTestId('override-button-disabled')
      expect(disabledBtn).toBeInTheDocument()
      expect(disabledBtn).toBeDisabled()
      expect(disabledBtn).toHaveAttribute(
        'title',
        'Supervisor role required to manual override'
      )
    })

    expect(screen.queryByTestId('override-action-button')).not.toBeInTheDocument()
  })

  it('enables Manual Override button when active role is Supervisor', async () => {
    renderApp('supervisor')

    // Wait for queue to populate
    await waitFor(() => {
      expect(screen.getByText('ORD-1002')).toBeInTheDocument()
    })

    // Open detail drawer for order ORD-1002
    const inspectBtn = screen.getByRole('button', { name: /review order ord-1002/i })
    fireEvent.click(inspectBtn)

    // Verify enabled override button is rendered
    await waitFor(() => {
      const actionBtn = screen.getByTestId('override-action-button')
      expect(actionBtn).toBeInTheDocument()
      expect(actionBtn).not.toBeDisabled()
    })

    expect(screen.queryByTestId('override-button-disabled')).not.toBeInTheDocument()
  })

  it('renders RFC 9457 Forbidden error banner in ManualOverrideModal when override returns 403', async () => {
    // Intercept override endpoint to simulate 403 Forbidden
    server.use(
      http.post('*/v1/refunds/:refundId/override', () => {
        return HttpResponse.json(
          {
            type: 'urn:problem:forbidden',
            title: 'Forbidden',
            status: 403,
            detail: 'Supervisor role required to perform manual overrides.',
            instance: '/v1/refunds/ref-102/override',
          },
          { status: 403 }
        )
      })
    )

    renderApp('supervisor')

    // Wait for queue table
    await waitFor(() => {
      expect(screen.getByText('ORD-1002')).toBeInTheDocument()
    })

    // Open drawer
    const inspectBtn = screen.getByRole('button', { name: /review order ord-1002/i })
    fireEvent.click(inspectBtn)

    // Click Manual Override
    const overrideTriggerBtn = await screen.findByTestId('override-action-button')
    fireEvent.click(overrideTriggerBtn)

    // Wait for modal
    await screen.findByText('Manual Decision Override')

    // Fill out form
    const textarea = screen.getByLabelText(/override justification/i)
    fireEvent.change(textarea, { target: { value: 'Valid justification note' } })

    const confirmCheckbox = screen.getByLabelText(/i confirm this manual decision override/i)
    fireEvent.click(confirmCheckbox)

    // Submit
    const submitBtn = screen.getByRole('button', { name: /submit override/i })
    fireEvent.click(submitBtn)

    // Verify 403 error banner is displayed
    const errorBanner = await screen.findByTestId('override-error-banner')
    expect(errorBanner).toBeInTheDocument()
    expect(errorBanner).toHaveTextContent('Forbidden')
    expect(errorBanner).toHaveTextContent(
      'Supervisor role required to perform manual overrides.'
    )
  })
})
