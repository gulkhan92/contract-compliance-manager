import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { AuthProvider } from '@/auth/AuthContext'

import { LoginPage } from './LoginPage'

const mockPost = vi.fn()

vi.mock('@/lib/api-client', () => ({
  apiClient: {
    GET: vi.fn().mockResolvedValue({ error: { detail: 'not authenticated' } }),
    POST: (...args: unknown[]) => mockPost(...args),
  },
  setAccessToken: vi.fn(),
  getAccessToken: vi.fn(() => null),
  setRefreshHandler: vi.fn(),
  apiOrigin: 'http://localhost:8000',
}))

function renderLoginPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/login']}>
        <AuthProvider>
          <LoginPage />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('LoginPage', () => {
  it('shows an error message when the credentials are rejected', async () => {
    mockPost.mockImplementation((path: string) => {
      if (path === '/api/v1/auth/refresh') {
        return Promise.resolve({ error: { detail: 'no session' } })
      }
      if (path === '/api/v1/auth/login') {
        return Promise.resolve({ error: { detail: 'Incorrect email or password.' } })
      }
      return Promise.resolve({ error: { detail: 'unexpected' } })
    })

    const user = userEvent.setup()
    renderLoginPage()

    await waitFor(() => screen.getByLabelText(/email/i))
    await user.type(screen.getByLabelText(/email/i), 'wrong@example.com')
    await user.type(screen.getByLabelText(/password/i), 'wrong-password')
    await user.click(screen.getByRole('button', { name: /sign in/i }))

    await waitFor(() => {
      expect(screen.getByText(/incorrect email or password/i)).toBeInTheDocument()
    })
  })

  it('submits the entered credentials to the login endpoint', async () => {
    mockPost.mockImplementation((path: string) => {
      if (path === '/api/v1/auth/refresh') {
        return Promise.resolve({ error: { detail: 'no session' } })
      }
      if (path === '/api/v1/auth/login') {
        return Promise.resolve({ data: { access_token: 'fake-token', token_type: 'bearer' } })
      }
      return Promise.resolve({ error: { detail: 'unexpected' } })
    })

    const user = userEvent.setup()
    renderLoginPage()

    await waitFor(() => screen.getByLabelText(/email/i))
    await user.type(screen.getByLabelText(/email/i), 'admin@example.com')
    await user.type(screen.getByLabelText(/password/i), 'correct horse battery staple')
    await user.click(screen.getByRole('button', { name: /sign in/i }))

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith(
        '/api/v1/auth/login',
        expect.objectContaining({
          body: { email: 'admin@example.com', password: 'correct horse battery staple' },
        }),
      )
    })
  })
})
