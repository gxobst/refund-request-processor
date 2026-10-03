import * as React from 'react'

export type UserRole = 'agent' | 'supervisor'

export interface RoleContextType {
  role: UserRole
  setRole: (role: UserRole) => void
  isSupervisor: boolean
}

export const RoleContext = React.createContext<RoleContextType | undefined>(undefined)

const STORAGE_KEY = 'user_role'
const DEFAULT_ROLE: UserRole = 'supervisor'

/**
 * Returns the currently active user role from localStorage, defaulting to 'supervisor'.
 * Can be called outside React component trees (e.g. by apiClient).
 */
export function getActiveUserRole(): UserRole {
  if (typeof window === 'undefined' || !window.localStorage) {
    return DEFAULT_ROLE
  }
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY)
    if (saved === 'agent' || saved === 'supervisor') {
      return saved
    }
  } catch {
    // Fall back if localStorage is disabled or restricted
  }
  return DEFAULT_ROLE
}

export interface RoleProviderProps {
  children: React.ReactNode
  initialRole?: UserRole
}

export function RoleProvider({ children, initialRole }: RoleProviderProps) {
  const [role, setRoleState] = React.useState<UserRole>(() => {
    if (initialRole) return initialRole
    return getActiveUserRole()
  })

  const setRole = React.useCallback((newRole: UserRole) => {
    setRoleState(newRole)
    if (typeof window !== 'undefined' && window.localStorage) {
      try {
        window.localStorage.setItem(STORAGE_KEY, newRole)
      } catch {
        // Ignore storage exceptions
      }
    }
  }, [])

  const isSupervisor = role === 'supervisor'

  const value = React.useMemo<RoleContextType>(
    () => ({
      role,
      setRole,
      isSupervisor,
    }),
    [role, setRole, isSupervisor]
  )

  return <RoleContext.Provider value={value}>{children}</RoleContext.Provider>
}

/**
 * Hook to access current role and switcher action.
 * Returns safe fallback if used outside of a RoleProvider.
 */
export function useUserRole(): RoleContextType {
  const context = React.useContext(RoleContext)
  if (!context) {
    const active = getActiveUserRole()
    return {
      role: active,
      setRole: (newRole: UserRole) => {
        if (typeof window !== 'undefined' && window.localStorage) {
          try {
            window.localStorage.setItem(STORAGE_KEY, newRole)
          } catch {
            // Ignore storage exceptions
          }
        }
      },
      isSupervisor: active === 'supervisor',
    }
  }
  return context
}
