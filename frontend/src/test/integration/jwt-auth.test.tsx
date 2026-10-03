import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/mocks/server'
import {
  RoleProvider,
  useUserRole,
  decodeTokenClaims,
  getAuthToken,
} from '@/context/RoleContext'
import { apiClient } from '@/services/apiClient'
import { Header } from '@/components/layout/Header'

function createTestToken(payload: Record<string, unknown>): string {
  const header = { alg: 'HS256', typ: 'JWT' }
  const b64 = (obj: object) =>
    btoa(JSON.stringify(obj))
      .replace(/\+/g, '-')
      .replace(/\//g, '_')
      .replace(/=+$/, '')
  return `${b64(header)}.${b64(payload)}.test_signature`
}

function RoleTestConsumer() {
  const { role, isSupervisor, authToken, setAuthToken, userSub } = useUserRole()

  return (
    <div>
      <span data-testid="consumer-role">{role}</span>
      <span data-testid="consumer-supervisor">{isSupervisor ? 'true' : 'false'}</span>
      <span data-testid="consumer-sub">{userSub || 'none'}</span>
      <span data-testid="consumer-token">{authToken || 'none'}</span>
      <button
        data-testid="set-supervisor-token"
        onClick={() => {
          const token = createTestToken({
            sub: 'sub-sup-101',
            'cognito:groups': ['supervisors'],
            'cognito:username': 'sup_jane',
            token_use: 'id',
          })
          setAuthToken(token)
        }}
      >
        Set Supervisor Token
      </button>
      <button
        data-testid="set-agent-token"
        onClick={() => {
          const token = createTestToken({
            sub: 'sub-agent-202',
            'cognito:groups': ['agents'],
            'cognito:username': 'agent_bob',
            token_use: 'id',
          })
          setAuthToken(token)
        }}
      >
        Set Agent Token
      </button>
      <button
        data-testid="clear-token"
        onClick={() => setAuthToken(null)}
      >
        Clear Token
      </button>
    </div>
  )
}

describe('Amazon Cognito and OAuth2 JWT Authentication Provider Integration', () => {
  beforeEach(() => {
    window.localStorage.clear()
  })

  describe('decodeTokenClaims', () => {
    it('decodes standard payload claims with cognito:groups', () => {
      const token = createTestToken({
        sub: 'usr-42',
        'cognito:groups': ['supervisors'],
        'cognito:username': 'alice',
        exp: 1700000000,
      })
      const claims = decodeTokenClaims(token)
      expect(claims).not.toBeNull()
      expect(claims?.sub).toBe('usr-42')
      expect(claims?.username).toBe('alice')
      expect(claims?.groups).toEqual(['supervisors'])
      expect(claims?.exp).toBe(1700000000)
    })

    it('decodes roles array fallback if cognito:groups is missing', () => {
      const token = createTestToken({
        sub: 'usr-99',
        roles: ['admin'],
      })
      const claims = decodeTokenClaims(token)
      expect(claims?.groups).toEqual(['admin'])
      expect(claims?.sub).toBe('usr-99')
    })

    it('returns null on invalid token formats', () => {
      expect(decodeTokenClaims('')).toBeNull()
      expect(decodeTokenClaims('single-part')).toBeNull()
      expect(decodeTokenClaims('two.parts')).toBeNull()
      expect(decodeTokenClaims('not.valid!base64.signature')).toBeNull()
    })
  })

  describe('RoleContext and Token State Management', () => {
    it('manages authToken and synchronizes role from supervisor and agent claims', () => {
      render(
        <RoleProvider>
          <RoleTestConsumer />
        </RoleProvider>
      )

      expect(screen.getByTestId('consumer-token')).toHaveTextContent('none')
      expect(screen.getByTestId('consumer-sub')).toHaveTextContent('none')

      // Set supervisor token
      fireEvent.click(screen.getByTestId('set-supervisor-token'))
      expect(screen.getByTestId('consumer-role')).toHaveTextContent('supervisor')
      expect(screen.getByTestId('consumer-supervisor')).toHaveTextContent('true')
      expect(screen.getByTestId('consumer-sub')).toHaveTextContent('sub-sup-101')
      expect(window.localStorage.getItem('auth_token')).toBeTruthy()

      // Set agent token
      fireEvent.click(screen.getByTestId('set-agent-token'))
      expect(screen.getByTestId('consumer-role')).toHaveTextContent('agent')
      expect(screen.getByTestId('consumer-supervisor')).toHaveTextContent('false')
      expect(screen.getByTestId('consumer-sub')).toHaveTextContent('sub-agent-202')

      // Clear token
      fireEvent.click(screen.getByTestId('clear-token'))
      expect(screen.getByTestId('consumer-token')).toHaveTextContent('none')
      expect(screen.getByTestId('consumer-sub')).toHaveTextContent('none')
      expect(window.localStorage.getItem('auth_token')).toBeNull()
    })

    it('initializes from cached localStorage auth_token', () => {
      const token = createTestToken({
        sub: 'cached-user-123',
        'cognito:groups': ['supervisors'],
      })
      window.localStorage.setItem('auth_token', token)

      render(
        <RoleProvider>
          <RoleTestConsumer />
        </RoleProvider>
      )

      expect(screen.getByTestId('consumer-role')).toHaveTextContent('supervisor')
      expect(screen.getByTestId('consumer-sub')).toHaveTextContent('cached-user-123')
      expect(getAuthToken()).toBe(token)
    })
  })

  describe('apiClient Bearer Token Injection', () => {
    it('automatically attaches Authorization: Bearer <token> when auth_token is stored', async () => {
      let capturedAuthHeader: string | null = null

      server.use(
        http.get('http://localhost:8000/api/test-auth', ({ request }) => {
          capturedAuthHeader = request.headers.get('Authorization')
          return HttpResponse.json({ status: 'ok' })
        })
      )

      const token = createTestToken({ sub: 'usr-api-1', 'cognito:groups': ['supervisors'] })
      window.localStorage.setItem('auth_token', token)

      await apiClient.get('/api/test-auth')
      expect(capturedAuthHeader).toBe(`Bearer ${token}`)
    })

    it('does not overwrite existing Authorization header if explicitly provided', async () => {
      let capturedAuthHeader: string | null = null

      server.use(
        http.get('http://localhost:8000/api/test-auth-custom', ({ request }) => {
          capturedAuthHeader = request.headers.get('Authorization')
          return HttpResponse.json({ status: 'ok' })
        })
      )

      const storedToken = createTestToken({ sub: 'stored-token' })
      window.localStorage.setItem('auth_token', storedToken)

      await apiClient.get('/api/test-auth-custom', {
        headers: { Authorization: 'Bearer explicit-override-token' },
      })
      expect(capturedAuthHeader).toBe('Bearer explicit-override-token')
    })

    it('omits Authorization header when no auth_token exists', async () => {
      let capturedAuthHeader: string | null = null

      server.use(
        http.get('http://localhost:8000/api/test-no-auth', ({ request }) => {
          capturedAuthHeader = request.headers.get('Authorization')
          return HttpResponse.json({ status: 'ok' })
        })
      )

      window.localStorage.removeItem('auth_token')
      await apiClient.get('/api/test-no-auth')
      expect(capturedAuthHeader).toBeNull()
    })
  })

  describe('Header Component Authentication Status and Demo Toggle', () => {
    it('renders auth status badge and toggles demo Cognito authentication', async () => {
      render(
        <RoleProvider>
          <Header />
        </RoleProvider>
      )

      // Initial state: simulated / unauthenticated
      const badge = screen.getByTestId('auth-status-badge')
      expect(badge).toBeInTheDocument()
      expect(badge).toHaveTextContent(/Dev Mode: Simulated/i)

      const authButton = screen.getByTestId('auth-token-button')
      expect(authButton).toBeInTheDocument()
      expect(authButton).toHaveTextContent('Sign in with Cognito (Demo)')

      // Click to sign in
      fireEvent.click(authButton)

      // Badge should update to connected with userSub
      await waitFor(() => {
        expect(badge).toHaveTextContent(/Cognito: Connected/i)
      })
      expect(badge).toHaveTextContent('demo-supervisor-01')
      expect(authButton).toHaveTextContent('Sign out')
      expect(window.localStorage.getItem('auth_token')).toBeTruthy()

      // Click to sign out
      fireEvent.click(authButton)

      await waitFor(() => {
        expect(badge).toHaveTextContent(/Dev Mode: Simulated/i)
      })
      expect(authButton).toHaveTextContent('Sign in with Cognito (Demo)')
      expect(window.localStorage.getItem('auth_token')).toBeNull()
    })
  })
})
