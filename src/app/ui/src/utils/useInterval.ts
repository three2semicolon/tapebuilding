/**
 * useInterval - call a callback every `delay` ms. When delay is 0 or falsy,
 * no timer runs. Cleans up on unmount.
 */

import { useEffect, useRef } from 'react'

export function useInterval(callback: () => void, delay: number | null) {
  const saved = useRef(callback)

  useEffect(() => {
    saved.current = callback
  }, [callback])

  useEffect(() => {
    if (!delay) return
    const id = setInterval(() => saved.current(), delay)
    return () => clearInterval(id)
  }, [delay])
}
