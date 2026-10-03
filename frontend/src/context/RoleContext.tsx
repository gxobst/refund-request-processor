import * as React from 'react'

export type UserRole = 'agent' | 'supervisor'

export interface DecodedTokenClaims {
  groups: string[]
  username?: string
  sub?: string
  exp?: number
  [key: string]: unknown
}

export interface RoleContextType {
  role: UserRole
  setRole: (role: UserRole) => void
  isSupervisor: boolean
  authToken: string | null
  setAuthToken: (token: string | null) => void
  userSub: string | null
}

export const RoleContext = React.createContext<RoleContextType | undefined>(undefined)

const ROLE_STORAGE_KEY = 'user_role'
const AUTH_TOKEN_KEY = 'auth_token'
const DEFAULT_ROLE: UserRole = 'supervisor'

/**
 * Decodes base64url JWT payload claims using standard browser web APIs (atob, JSON.parse).
 * Pure implementation without external third-party dependencies.
 */
export function decodeTokenClaims(token: string): DecodedTokenClaims | null {
  if (!token || typeof token !== 'string') return null
  try {
    const parts = token.trim().split('.')
    if (parts.length !== 3) return null

    let payloadBase64 = parts[1].replace(/-/g, '+').replace(/_/g, '/')
    const pad = payloadBase64.length % 4
    if (pad > 0) {
      payloadBase64 += '='.repeat(4 - pad)
    }

    let jsonStr: string
    try {
      jsonStr = decodeURIComponent(
        Array.from(atob(payloadBase64))
          .map((c) => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2))
          .join('')
      )
    } catch {
      jsonStr = atob(payloadBase64)
    }

    const raw = JSON.parse(jsonStr)
    if (!raw || typeof raw !== 'object') return null

    const rawGroups = raw['cognito:groups'] || raw['roles'] || []
    const groups: string[] = Array.isArray(rawGroups)
      ? rawGroups.map(String)
      : typeof rawGroups === 'string'
      ? [rawGroups]
      : []

    return {
      ...raw,
      groups,
      username: raw.username || raw['cognito:username'] || undefined,
      sub: raw.sub || undefined,
      exp: typeof raw.exp === 'number' ? raw.exp : undefined,
    }
  } catch {
    return null
  }
}

/**
 * Returns the currently active user role from localStorage, defaulting to 'supervisor'.
 * Can be called outside React component trees (e.g. by apiClient).
 */
export function getActiveUserRole(): UserRole {
  if (typeof window === 'undefined' || !window.localStorage) {
    return DEFAULT_ROLE
  }
  try {
    const saved = window.localStorage.getItem(ROLE_STORAGE_KEY)
    if (saved === 'agent' || saved === 'supervisor') {
      return saved
    }
  } catch {
    // Fall back if localStorage is disabled or restricted
  }
  return DEFAULT_ROLE
}

/**
 * Returns the currently cached JWT auth token from localStorage.
 * Callable outside React components (e.g. by apiClient request interceptor).
 */
export function getAuthToken(): string | null {
  if (typeof window === 'undefined' || !window.localStorage) {
    return null
  }
  try {
    return window.localStorage.getItem(AUTH_TOKEN_KEY)
  } catch {
    return null
  }
}

export interface RoleProviderProps {
  children: React.ReactNode
  initialRole?: UserRole
  initialAuthToken?: string | null
}

export function RoleProvider({ children, initialRole, initialAuthToken }: RoleProviderProps) {
  const [authToken, setAuthTokenState] = React.useState<string | null>(() => {
    if (initialAuthToken !== undefined) return initialAuthToken
    return getAuthToken()
  })

  const [role, setRoleState] = React.useState<UserRole>(() => {
    if (initialRole) return initialRole
    const token = initialAuthToken !== undefined ? initialAuthToken : getAuthToken()
    if (token) {
      const claims = decodeTokenClaims(token)
      if (claims) {
        const hasSupervisor = claims.groups.some((g) =>
          ['supervisors', 'supervisor', 'admin'].includes(g.toLowerCase().trim())
        )
        return hasSupervisor ? 'supervisor' : 'agent'
      }
    }
    return getActiveUserRole()
  })

  const [userSub, setUserSub] = React.useState<string | null>(() => {
    const token = initialAuthToken !== undefined ? initialAuthToken : getAuthToken()
    if (token) {
      const claims = decodeTokenClaims(token)
      return claims?.sub || claims?.username || null
    }
    return null
  })

  const setRole = React.useCallback((newRole: UserRole) => {
    setRoleState(newRole)
    if (typeof window !== 'undefined' && window.localStorage) {
      try {
        window.localStorage.setItem(ROLE_STORAGE_KEY, newRole)
      } catch {
        // Ignore storage exceptions
      }
    }
  }, [])

  const setAuthToken = React.useCallback(
    (token: string | null) => {
      setAuthTokenState(token)
      if (token) {
        if (typeof window !== 'undefined' && window.localStorage) {
          try {
            window.localStorage.setItem(AUTH_TOKEN_KEY, token)
          } catch {
            // Ignore storage exceptions
          }
        }
        const claims = decodeTokenClaims(token)
        if (claims) {
          const hasSupervisor = claims.groups.some((g) =>
            ['supervisors', 'supervisor', 'admin'].includes(g.toLowerCase().trim())
          )
          const newRole: UserRole = hasSupervisor ? 'supervisor' : 'agent'
          setRoleState(newRole)
          if (typeof window !== 'undefined' && window.localStorage) {
            try {
              window.localStorage.setItem(ROLE_STORAGE_KEY, newRole)
            } catch {
              // Ignore storage exceptions
            }
          }
          setUserSub(claims.sub || claims.username || null)
        } else {
          setUserSub(null)
        }
      } else {
        if (typeof window !== 'undefined' && window.localStorage) {
          try {
            window.localStorage.removeItem(AUTH_TOKEN_KEY)
          } catch {
            // Ignore storage exceptions
          }
        }
        setUserSub(null)
      }
    },
    []
  )

  const isSupervisor = role === 'supervisor'

  const value = React.useMemo<RoleContextType>(
    () => ({
      role,
      setRole,
      isSupervisor,
      authToken,
      setAuthToken,
      userSub,
    }),
    [role, setRole, isSupervisor, authToken, setAuthToken, userSub]
  )

  return <RoleContext.Provider value={value}>{children}</RoleContext.Provider>
}

/**
 * Hook to access current role and authentication state.
 * Returns safe fallback if used outside of a RoleProvider.
 */
export function useUserRole(): RoleContextType {
  const context = React.useContext(RoleContext)
  if (!context) {
    const active = getActiveUserRole()
    const token = getAuthToken()
    const claims = token ? decodeTokenClaims(token) : null
    return {
      role: active,
      setRole: (newRole: UserRole) => {
        if (typeof window !== 'undefined' && window.localStorage) {
          try {
            window.localStorage.setItem(ROLE_STORAGE_KEY, newRole)
          } catch {
            // Ignore storage exceptions
          }
        }
      },
      isSupervisor: active === 'supervisor',
      authToken: token,
      setAuthToken: (newToken: string | null) => {
        if (typeof window !== 'undefined' && window.localStorage) {
          try {
            if (newToken) {
              window.localStorage.setItem(AUTH_TOKEN_KEY, newToken)
            } else {
              window.localStorage.removeItem(AUTH_TOKEN_KEY)
            }
          } catch {
            // Ignore storage exceptions
          }
        }
      },
      userSub: claims?.sub || claims?.username || null,
    }
  }
  return context
}
