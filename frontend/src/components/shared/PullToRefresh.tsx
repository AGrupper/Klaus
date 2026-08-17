/**
 * PullToRefresh — pulling the page down refetches, which is what Amit
 * expected it to do all along ("can you just make it so the app refreshes
 * when scrolling down").
 *
 * Works on the app's own scroll container rather than the document: iOS's
 * native document rubber-band is disabled (overscroll-behavior in index.css),
 * so this owns the gesture end to end and nothing else can be dragged into
 * view by it.
 *
 * Only engages when the scroller is already at the top and the finger moves
 * downward, so it never competes with ordinary scrolling.
 */
import { useCallback, useRef, useState, type ReactNode } from 'react'
import { Loader2 } from 'lucide-react'
import { tapFeedback } from '../../utils/haptics'

/** Pull past this to trigger; the indicator is fully opaque here. */
const TRIGGER_PX = 72
/** Hard cap so the content can't be dragged arbitrarily far. */
const MAX_PULL_PX = 110
/** Damping — the content follows at less than finger speed, like iOS. */
const RESISTANCE = 0.45

interface PullToRefreshProps {
  onRefresh: () => Promise<unknown>
  children: ReactNode
  className?: string
  style?: React.CSSProperties
}

export function PullToRefresh({ onRefresh, children, className, style }: PullToRefreshProps) {
  const scroller = useRef<HTMLDivElement>(null)
  const startY = useRef<number | null>(null)
  const [pull, setPull] = useState(0)
  const [refreshing, setRefreshing] = useState(false)

  const onTouchStart = useCallback((event: React.TouchEvent) => {
    // Only arm the gesture when there is nothing above us to scroll to.
    if ((scroller.current?.scrollTop ?? 0) > 0 || refreshing) {
      startY.current = null
      return
    }
    startY.current = event.touches[0]?.clientY ?? null
  }, [refreshing])

  const onTouchMove = useCallback((event: React.TouchEvent) => {
    if (startY.current === null) return
    const y = event.touches[0]?.clientY
    if (y === undefined) return
    const delta = y - startY.current
    if (delta <= 0) {
      // Pulling up again — hand the gesture back to normal scrolling.
      setPull(0)
      startY.current = null
      return
    }
    setPull(Math.min(delta * RESISTANCE, MAX_PULL_PX))
  }, [])

  const finish = useCallback(async () => {
    if (startY.current === null) return
    const travelled = pull
    startY.current = null
    if (travelled < TRIGGER_PX) {
      setPull(0)
      return
    }
    tapFeedback()
    setRefreshing(true)
    setPull(TRIGGER_PX)
    try {
      await onRefresh()
    } finally {
      setRefreshing(false)
      setPull(0)
    }
  }, [onRefresh, pull])

  const active = pull > 0 || refreshing
  const progress = Math.min(pull / TRIGGER_PX, 1)

  return (
    <div
      ref={scroller}
      className={className}
      style={{ ...style, position: 'relative' }}
      onTouchStart={onTouchStart}
      onTouchMove={onTouchMove}
      onTouchEnd={finish}
      onTouchCancel={() => {
        startY.current = null
        setPull(0)
      }}
    >
      {/* Indicator lives above the content and is revealed by the pull. */}
      <div
        aria-hidden={!active}
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          height: `${TRIGGER_PX}px`,
          marginTop: `-${TRIGGER_PX}px`,
          transform: `translateY(${pull}px)`,
          transition: startY.current === null ? 'transform 0.28s var(--spring)' : 'none',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: 'var(--muted)',
          opacity: progress,
          pointerEvents: 'none',
        }}
      >
        <Loader2
          size={20}
          strokeWidth={2}
          style={{
            animation: refreshing ? 'spin 0.8s linear infinite' : undefined,
            transform: refreshing ? undefined : `rotate(${progress * 270}deg)`,
          }}
        />
      </div>
      <div
        style={{
          transform: `translateY(${pull}px)`,
          transition: startY.current === null ? 'transform 0.28s var(--spring)' : 'none',
        }}
      >
        {children}
      </div>
    </div>
  )
}
