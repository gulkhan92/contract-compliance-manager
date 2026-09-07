import createClient, { type Middleware } from 'openapi-fetch'

import type { paths } from './api-schema'

// VITE_API_BASE_URL (see .env.example) is documented as the full
// `.../api/v1` base; the generated `paths` keys already embed that prefix,
// so openapi-fetch's own baseUrl must be just the origin. Falling back to
// localhost:8000 also means the docker-compose demo works with zero
// frontend build configuration: nginx serves this bundle to the browser,
// which then reaches the api container's own published host port directly.
function resolveOrigin(): string {
  const configured = import.meta.env.VITE_API_BASE_URL as string | undefined
  if (!configured) return 'http://localhost:8000'
  return configured.replace(/\/api\/v1\/?$/, '')
}

export const apiOrigin = resolveOrigin()

let accessToken: string | null = null

export function setAccessToken(token: string | null): void {
  accessToken = token
}

export function getAccessToken(): string | null {
  return accessToken
}

/** Set by AuthContext once mounted; calls POST /auth/refresh (cookie-based)
 * and returns the new access token, or null if the refresh itself failed. */
let refreshHandler: (() => Promise<string | null>) | null = null

export function setRefreshHandler(handler: (() => Promise<string | null>) | null): void {
  refreshHandler = handler
}

const AUTH_EXEMPT_PATHS = ['/api/v1/auth/login', '/api/v1/auth/register', '/api/v1/auth/refresh']

// Shared across concurrent 401s so a burst of requests (e.g. a dashboard
// firing several queries at once right as the access token expires)
// triggers exactly one refresh call, not one per request.
let inFlightRefresh: Promise<string | null> | null = null

function refreshOnce(): Promise<string | null> {
  if (!refreshHandler) return Promise.resolve(null)
  if (!inFlightRefresh) {
    inFlightRefresh = refreshHandler().finally(() => {
      inFlightRefresh = null
    })
  }
  return inFlightRefresh
}

const authMiddleware: Middleware = {
  async onRequest({ request }) {
    if (accessToken && !AUTH_EXEMPT_PATHS.some((p) => request.url.includes(p))) {
      request.headers.set('Authorization', `Bearer ${accessToken}`)
    }
    return request
  },
  async onResponse({ request, response }) {
    const isExempt = AUTH_EXEMPT_PATHS.some((p) => request.url.includes(p))
    if (response.status !== 401 || isExempt || !refreshHandler) {
      return response
    }

    const newToken = await refreshOnce()
    if (!newToken) return response

    const retryRequest = new Request(request, {
      headers: new Headers(request.headers),
    })
    retryRequest.headers.set('Authorization', `Bearer ${newToken}`)
    return fetch(retryRequest)
  },
}

export const apiClient = createClient<paths>({
  baseUrl: resolveOrigin(),
  credentials: 'include',
})

apiClient.use(authMiddleware)
