import { createContext, use, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'

import { apiClient, setAccessToken, setRefreshHandler } from '@/lib/api-client'
import type { components } from '@/lib/api-schema'

type UserPublic = components['schemas']['UserPublic']

interface AuthContextValue {
  user: UserPublic | null
  isBootstrapping: boolean
  login: (email: string, password: string) => Promise<void>
  register: (orgName: string, email: string, password: string, fullName: string) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

async function fetchCurrentUser(): Promise<UserPublic | null> {
  const { data, error } = await apiClient.GET('/api/v1/auth/me')
  if (error) return null
  return data
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserPublic | null>(null)
  const [isBootstrapping, setIsBootstrapping] = useState(true)

  // Refresh tokens are single-use (rotated server-side on every call), so
  // two near-simultaneous refresh() calls racing each other is a real
  // failure mode, not just wasted work — the loser gets a 401 off a token
  // the winner already rotated out from under it. React StrictMode's
  // dev-only double-invocation of the mount effect below hits this exact
  // race every time; sharing one in-flight promise across callers (this
  // effect, and api-client's 401-retry handler) closes it for good.
  const inFlightRefresh = useRef<Promise<string | null> | null>(null)

  const refresh = useCallback((): Promise<string | null> => {
    if (!inFlightRefresh.current) {
      inFlightRefresh.current = (async () => {
        const { data, error } = await apiClient.POST('/api/v1/auth/refresh')
        if (error || !data) {
          setAccessToken(null)
          setUser(null)
          return null
        }
        setAccessToken(data.access_token)
        return data.access_token
      })().finally(() => {
        inFlightRefresh.current = null
      })
    }
    return inFlightRefresh.current
  }, [])

  useEffect(() => {
    setRefreshHandler(refresh)
    return () => setRefreshHandler(null)
  }, [refresh])

  useEffect(() => {
    // The access token lives only in memory, so a hard page reload loses
    // it — attempt one silent refresh on mount using the httpOnly refresh
    // cookie, which does survive a reload, to restore the session.
    let cancelled = false
    async function bootstrap() {
      const token = await refresh()
      if (cancelled) return
      if (token) {
        const currentUser = await fetchCurrentUser()
        if (!cancelled) setUser(currentUser)
      }
      if (!cancelled) setIsBootstrapping(false)
    }
    void bootstrap()
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    const { data, error } = await apiClient.POST('/api/v1/auth/login', {
      body: { email, password },
    })
    if (error || !data) {
      throw new Error(
        (error as { detail?: string } | undefined)?.detail ?? 'Incorrect email or password.',
      )
    }
    setAccessToken(data.access_token)
    const currentUser = await fetchCurrentUser()
    setUser(currentUser)
  }, [])

  const register = useCallback(
    async (orgName: string, email: string, password: string, fullName: string) => {
      const { data, error } = await apiClient.POST('/api/v1/auth/register', {
        body: { org_name: orgName, email, password, full_name: fullName },
      })
      if (error || !data) {
        throw new Error(
          (error as { detail?: string } | undefined)?.detail ?? 'Could not create your account.',
        )
      }
      setAccessToken(data.access_token)
      const currentUser = await fetchCurrentUser()
      setUser(currentUser)
    },
    [],
  )

  const logout = useCallback(async () => {
    await apiClient.POST('/api/v1/auth/logout')
    setAccessToken(null)
    setUser(null)
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({ user, isBootstrapping, login, register, logout }),
    [user, isBootstrapping, login, register, logout],
  )

  return <AuthContext value={value}>{children}</AuthContext>
}

export function useAuth(): AuthContextValue {
  const context = use(AuthContext)
  if (!context) throw new Error('useAuth must be used within an AuthProvider')
  return context
}
