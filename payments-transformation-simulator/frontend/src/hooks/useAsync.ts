/** Data-loading hooks.
 *
 * Deliberately small: one hook for a request tied to a dependency list, one for
 * an imperative action. No global cache, so a reload always shows the engine's
 * real current state rather than something remembered.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import { ApiError } from '../api/client'

export interface AsyncState<T> {
  data: T | null
  loading: boolean
  error: ApiError | null
  reload: () => void
  setData: (value: T) => void
}

export function useAsync<T>(
  loader: (signal: AbortSignal) => Promise<T>,
  deps: unknown[] = [],
  options: { enabled?: boolean } = {},
): AsyncState<T> {
  const enabled = options.enabled !== false
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(enabled)
  const [error, setError] = useState<ApiError | null>(null)
  const [nonce, setNonce] = useState(0)
  const loaderRef = useRef(loader)
  loaderRef.current = loader

  useEffect(() => {
    if (!enabled) {
      setLoading(false)
      return
    }
    const controller = new AbortController()
    let active = true
    setLoading(true)
    loaderRef
      .current(controller.signal)
      .then((result) => {
        if (!active) return
        setData(result)
        setError(null)
      })
      .catch((cause: unknown) => {
        if (!active) return
        if ((cause as Error)?.name === 'AbortError') return
        setError(
          cause instanceof ApiError
            ? cause
            : new ApiError(0, 'UNKNOWN', (cause as Error)?.message ?? 'Unexpected error', null, null),
        )
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
      controller.abort()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce, enabled])

  const reload = useCallback(() => setNonce((n) => n + 1), [])
  return { data, loading, error, reload, setData }
}

export interface ActionState<TArgs extends unknown[], TResult> {
  run: (...args: TArgs) => Promise<TResult | null>
  pending: boolean
  error: ApiError | null
  reset: () => void
}

export function useAction<TArgs extends unknown[], TResult>(
  action: (...args: TArgs) => Promise<TResult>,
  options: { onSuccess?: (result: TResult) => void; onError?: (error: ApiError) => void } = {},
): ActionState<TArgs, TResult> {
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const optionsRef = useRef(options)
  optionsRef.current = options
  const actionRef = useRef(action)
  actionRef.current = action

  const run = useCallback(async (...args: TArgs): Promise<TResult | null> => {
    setPending(true)
    setError(null)
    try {
      const result = await actionRef.current(...args)
      optionsRef.current.onSuccess?.(result)
      return result
    } catch (cause) {
      const apiError =
        cause instanceof ApiError
          ? cause
          : new ApiError(0, 'UNKNOWN', (cause as Error)?.message ?? 'Unexpected error', null, null)
      setError(apiError)
      optionsRef.current.onError?.(apiError)
      return null
    } finally {
      setPending(false)
    }
  }, [])

  const reset = useCallback(() => setError(null), [])
  return { run, pending, error, reset }
}

/** Poll while `active` is true. Used while a payment is processing asynchronously. */
export function usePolling(callback: () => void, intervalMs: number, active: boolean): void {
  const callbackRef = useRef(callback)
  callbackRef.current = callback
  useEffect(() => {
    if (!active) return
    const id = window.setInterval(() => callbackRef.current(), intervalMs)
    return () => window.clearInterval(id)
  }, [intervalMs, active])
}

/** Debounce a changing value, for search-as-you-type. */
export function useDebounced<T>(value: T, delayMs = 220): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(value), delayMs)
    return () => window.clearTimeout(id)
  }, [value, delayMs])
  return debounced
}
