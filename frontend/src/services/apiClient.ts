import type { ProblemDetails, ValidationProblemDetails, InvalidParam } from '../types/api'

/**
 * ApiError wraps RFC 9457 ProblemDetails and ValidationProblemDetails errors
 * returned from backend endpoints or generated on network failures.
 */
export class ApiError extends Error {
  readonly status: number
  readonly problem: ProblemDetails | ValidationProblemDetails

  constructor(problem: ProblemDetails | ValidationProblemDetails) {
    super(problem.detail || problem.title)
    this.name = 'ApiError'
    this.status = problem.status
    this.problem = problem
    Object.setPrototypeOf(this, ApiError.prototype)
  }
}

/**
 * Type guard for ApiError instances.
 */
export function isApiError(err: unknown): err is ApiError {
  return err instanceof ApiError
}

/**
 * Type guard specifically for RFC 9457 ValidationProblemDetails errors (HTTP 422).
 */
export function isValidationProblem(
  err: unknown,
): err is ApiError & { problem: ValidationProblemDetails & { invalidParams: InvalidParam[] } } {
  if (!isApiError(err)) return false
  const p = err.problem as ValidationProblemDetails
  return Array.isArray(p.invalidParams) && p.invalidParams.length > 0
}

/**
 * Maps standard HTTP status codes to canonical titles when titles are omitted.
 */
function getDefaultTitle(status: number): string {
  switch (status) {
    case 400:
      return 'Bad Request'
    case 401:
      return 'Unauthorized'
    case 403:
      return 'Forbidden'
    case 404:
      return 'Not Found'
    case 405:
      return 'Method Not Allowed'
    case 409:
      return 'Conflict'
    case 413:
      return 'Payload Too Large'
    case 422:
      return 'Validation Error'
    case 500:
      return 'Internal Server Error'
    case 502:
      return 'Bad Gateway'
    case 503:
      return 'Service Unavailable'
    case 504:
      return 'Gateway Timeout'
    default:
      return status >= 500 ? 'Server Error' : 'Request Error'
  }
}

/**
 * Constructs an absolute API request URL from the configured base URL and endpoint path.
 */
export function buildUrl(path: string): string {
  let baseUrl = (import.meta.env?.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/+$/, '')

  if (typeof window !== 'undefined' && window.location?.hostname) {
    if (window.location.hostname === '127.0.0.1' && baseUrl.includes('localhost')) {
      baseUrl = baseUrl.replace('localhost', '127.0.0.1')
    } else if (window.location.hostname === 'localhost' && baseUrl.includes('127.0.0.1')) {
      baseUrl = baseUrl.replace('127.0.0.1', 'localhost')
    }
  }

  const cleanPath = path.startsWith('/') ? path : `/${path}`
  return `${baseUrl}${cleanPath}`
}

/**
 * Normalizes HTTP non-2xx error responses into RFC 9457 ProblemDetails or ValidationProblemDetails.
 */
async function parseErrorResponse(
  response: Response,
  path: string,
): Promise<ProblemDetails | ValidationProblemDetails> {
  let body: unknown = null
  const contentType = response.headers.get('content-type') || ''

  try {
    if (contentType.includes('json')) {
      body = await response.json()
    } else {
      body = await response.text()
    }
  } catch {
    body = null
  }

  // 1. Direct RFC 9457 ProblemDetails or ValidationProblemDetails
  if (
    body &&
    typeof body === 'object' &&
    'type' in body &&
    'title' in body &&
    'status' in body
  ) {
    const raw = body as Record<string, unknown>
    const problem: ProblemDetails | ValidationProblemDetails = {
      type: String(raw.type),
      title: String(raw.title),
      status: Number(raw.status) || response.status,
      detail: String(raw.detail ?? ''),
      instance: raw.instance ? String(raw.instance) : path,
      ...(Array.isArray(raw.invalidParams)
        ? { invalidParams: raw.invalidParams as InvalidParam[] }
        : {}),
    }
    return problem
  }

  // 2. FastAPI 422 Unprocessable Entity parameter validation error array: {"detail": [...]}
  if (
    response.status === 422 &&
    body &&
    typeof body === 'object' &&
    Array.isArray((body as Record<string, unknown>).detail)
  ) {
    const detailArray = (body as Record<string, unknown>).detail as Array<Record<string, unknown>>
    const invalidParams: InvalidParam[] = detailArray.map((err) => {
      let name = 'unknown'
      if (Array.isArray(err.loc)) {
        const filtered = err.loc.filter((part) => part !== 'body')
        name = filtered.length > 0 ? filtered.join('.') : err.loc.join('.')
      } else if (err.loc) {
        name = String(err.loc)
      } else if (err.name) {
        name = String(err.name)
      }
      const reason = String(err.msg || err.reason || 'Invalid parameter')
      return { name, reason }
    })

    const validationProblem: ValidationProblemDetails = {
      type: 'urn:problem:validation-error',
      title: 'Validation Error',
      status: 422,
      detail: 'One or more fields in the request body failed validation.',
      instance: path,
      invalidParams,
    }
    return validationProblem
  }

  // 3. FastAPI standard error format: {"detail": "..."}
  if (
    body &&
    typeof body === 'object' &&
    typeof (body as Record<string, unknown>).detail === 'string'
  ) {
    const problem: ProblemDetails = {
      type: `urn:problem:${response.status}`,
      title: response.statusText || getDefaultTitle(response.status),
      status: response.status,
      detail: (body as Record<string, unknown>).detail as string,
      instance: path,
    }
    return problem
  }

  // 4. Raw text, empty response, or unexpected JSON payload
  const detail =
    typeof body === 'string' && body.trim()
      ? body.trim()
      : response.statusText || getDefaultTitle(response.status)

  const fallbackProblem: ProblemDetails = {
    type: `urn:problem:${response.status}`,
    title: response.statusText || getDefaultTitle(response.status),
    status: response.status,
    detail,
    instance: path,
  }
  return fallbackProblem
}

/**
 * Dispatches an HTTP request with automatic JSON/multipart header handling
 * and RFC 9457 error normalization.
 */
export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const url = buildUrl(path)
  const isMultipart = options.body instanceof FormData

  const headers = new Headers(options.headers || {})

  if (!headers.has('Accept')) {
    headers.set('Accept', 'application/json, application/problem+json')
  }

  if (isMultipart) {
    // Browser fetch must generate the multipart boundary; do not override Content-Type
    headers.delete('Content-Type')
  } else if (!headers.has('Content-Type') && options.body !== undefined) {
    headers.set('Content-Type', 'application/json')
  }

  let response: Response
  try {
    response = await fetch(url, {
      ...options,
      headers,
    })
  } catch (networkErr: unknown) {
    const errorMsg =
      networkErr instanceof Error
        ? networkErr.message
        : 'Network connection failed or backend is unreachable.'

    const networkProblem: ProblemDetails = {
      type: 'urn:problem:network-error',
      title: 'Network Error',
      status: 0,
      detail: errorMsg,
      instance: path,
    }
    throw new ApiError(networkProblem)
  }

  if (!response.ok) {
    const problem = await parseErrorResponse(response, path)
    throw new ApiError(problem)
  }

  if (response.status === 204) {
    return undefined as T
  }

  const contentType = response.headers.get('content-type') || ''
  if (contentType.includes('json')) {
    return (await response.json()) as T
  }

  return (await response.text()) as unknown as T
}

/**
 * Centralized API client service methods.
 */
export const apiClient = {
  get: <T>(path: string, options?: RequestInit): Promise<T> =>
    request<T>(path, { ...options, method: 'GET' }),

  post: <T>(path: string, data?: unknown, options?: RequestInit): Promise<T> => {
    const body =
      data !== undefined
        ? typeof data === 'string'
          ? data
          : JSON.stringify(data)
        : undefined

    return request<T>(path, {
      ...options,
      method: 'POST',
      body,
    })
  },

  postMultipart: <T>(path: string, formData: FormData, options?: RequestInit): Promise<T> =>
    request<T>(path, {
      ...options,
      method: 'POST',
      body: formData,
    }),

  put: <T>(path: string, data?: unknown, options?: RequestInit): Promise<T> => {
    const body =
      data !== undefined
        ? typeof data === 'string'
          ? data
          : JSON.stringify(data)
        : undefined

    return request<T>(path, {
      ...options,
      method: 'PUT',
      body,
    })
  },

  delete: <T>(path: string, options?: RequestInit): Promise<T> =>
    request<T>(path, { ...options, method: 'DELETE' }),

  request,
}
