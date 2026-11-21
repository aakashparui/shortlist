/** Business / technical mode and theme, persisted per operator. */

import type { ReactNode } from 'react'
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'

import type { ViewMode } from '../api/types'

type Theme = 'dark' | 'light'

interface ViewModeValue {
  mode: ViewMode
  setMode: (mode: ViewMode) => void
  toggleMode: () => void
  isTechnical: boolean
  theme: Theme
  toggleTheme: () => void
}

const STORAGE_MODE = 'pts.viewMode'
const STORAGE_THEME = 'pts.theme'

const ViewModeContext = createContext<ViewModeValue | null>(null)

function readStored<T extends string>(key: string, fallback: T, allowed: readonly T[]): T {
  try {
    const stored = window.localStorage.getItem(key)
    if (stored && (allowed as readonly string[]).includes(stored)) return stored as T
  } catch {
    /* storage unavailable (private mode): fall through to the default */
  }
  return fallback
}

export function ViewModeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<ViewMode>(() =>
    readStored<ViewMode>(STORAGE_MODE, 'business', ['business', 'technical']),
  )
  const [theme, setTheme] = useState<Theme>(() => readStored<Theme>(STORAGE_THEME, 'dark', ['dark', 'light']))

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    try {
      window.localStorage.setItem(STORAGE_THEME, theme)
    } catch {
      /* ignore */
    }
  }, [theme])

  const setMode = useCallback((next: ViewMode) => {
    setModeState(next)
    try {
      window.localStorage.setItem(STORAGE_MODE, next)
    } catch {
      /* ignore */
    }
  }, [])

  const value = useMemo<ViewModeValue>(
    () => ({
      mode,
      setMode,
      toggleMode: () => setMode(mode === 'business' ? 'technical' : 'business'),
      isTechnical: mode === 'technical',
      theme,
      toggleTheme: () => setTheme(theme === 'dark' ? 'light' : 'dark'),
    }),
    [mode, setMode, theme],
  )

  return <ViewModeContext.Provider value={value}>{children}</ViewModeContext.Provider>
}

export function useViewMode(): ViewModeValue {
  const context = useContext(ViewModeContext)
  if (context) return context
  // Fallback so primitives stay usable in isolation (and in unit tests).
  return {
    mode: 'business',
    setMode: () => undefined,
    toggleMode: () => undefined,
    isTechnical: false,
    theme: 'dark',
    toggleTheme: () => undefined,
  }
}
