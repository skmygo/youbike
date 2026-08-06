import { useMemo, useState } from "react"

import type { PulsePoint } from "@/lib/api"
import { slotLabel } from "@/lib/status"

const W = 960
const H = 72
const MID = H / 2

export interface BaselinePoint {
  slot: number
  n_empty: number
  n_full: number
}

interface Props {
  points: PulsePoint[]
  /** 同一個星期幾的歷史常態，畫成輪廓線讓今天有比較基準 */
  baseline?: BaselinePoint[]
  /** 目前對齊的半小時槽（0..47），畫成黃色指針 */
  currentSlot?: number | null
  onSlotSelect?: (slot: number) => void
  label?: string
}

/**
 * 全市空滿脈搏帶：一天 48 個半小時槽，無車可借的站數向上、無位可還的站數
 * 向下。通勤雙峰在這條帶子上會直接長成兩個尖峰——這是命題痛點最短的證據。
 */
export function PulseRibbon({
  points,
  baseline,
  currentSlot,
  onSlotSelect,
  label,
}: Props) {
  const [hover, setHover] = useState<number | null>(null)

  const { bySlot, baseBySlot, max } = useMemo(() => {
    const bySlot = new Map<number, PulsePoint>()
    for (const p of points) bySlot.set(p.slot, p)
    const baseBySlot = new Map<number, BaselinePoint>()
    for (const p of baseline ?? []) baseBySlot.set(p.slot, p)
    const max = Math.max(
      10,
      ...points.map((p) => Math.max(p.n_empty, p.n_full)),
      ...(baseline ?? []).map((p) => Math.max(p.n_empty, p.n_full)),
    )
    return { bySlot, baseBySlot, max }
  }, [points, baseline])

  const bw = W / 48
  const scale = (v: number) => (v / max) * (MID - 6)
  const active = hover ?? currentSlot ?? null
  const activePoint = active != null ? bySlot.get(active) : undefined
  const activeBase = active != null ? baseBySlot.get(active) : undefined

  return (
    <div className="relative">
      <div className="mb-1 flex items-baseline justify-between">
        <span className="eyebrow">{label ?? "全市空滿脈搏 · 每半小時"}</span>
        <span className="num text-[11px] text-ink-dim">
          {activePoint ? (
            <>
              <span className="text-ink-faint">{slotLabel(activePoint.slot)}</span>
              <span className="ml-2 text-st-empty">無車 {activePoint.n_empty}</span>
              <span className="ml-2 text-st-full">無位 {activePoint.n_full}</span>
              {activeBase && (
                <span className="ml-2 text-ink-faint">
                  常態 {Math.round(activeBase.n_empty)}／{Math.round(activeBase.n_full)}
                </span>
              )}
            </>
          ) : (
            <span className="text-ink-faint">
              {baseline?.length ? "虛線是同一個星期幾的歷史常態" : "滑過查看各時段站數"}
            </span>
          )}
        </span>
      </div>

      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        className="h-[72px] w-full"
        onMouseLeave={() => setHover(null)}
        role="img"
        aria-label="全市各時段無車可借與無位可還的站數"
      >
        <line x1={0} y1={MID} x2={W} y2={MID} stroke="#253148" strokeWidth={1} />
        {[6, 12, 18].map((h) => (
          <line
            key={h}
            x1={(h * 2 * W) / 48}
            y1={0}
            x2={(h * 2 * W) / 48}
            y2={H}
            stroke="#1b2537"
            strokeWidth={1}
          />
        ))}

        {baseline && baseline.length > 0 && (
          <>
            <path
              d={linePath(baseBySlot, 48, bw, MID, scale, "n_empty", -1)}
              fill="none"
              stroke="#ff5c5c"
              strokeWidth={1}
              strokeDasharray="3 2"
              opacity={0.55}
            />
            <path
              d={linePath(baseBySlot, 48, bw, MID, scale, "n_full", 1)}
              fill="none"
              stroke="#4c8dff"
              strokeWidth={1}
              strokeDasharray="3 2"
              opacity={0.55}
            />
          </>
        )}

        {Array.from({ length: 48 }, (_, slot) => {
          const p = bySlot.get(slot)
          const x = slot * bw
          const isActive = active === slot
          return (
            <g key={slot}>
              {p && (
                <>
                  <rect
                    x={x + 0.6}
                    y={MID - scale(p.n_empty)}
                    width={bw - 1.2}
                    height={Math.max(scale(p.n_empty), p.n_empty > 0 ? 1 : 0)}
                    fill="#ff5c5c"
                    opacity={isActive ? 1 : 0.75}
                  />
                  <rect
                    x={x + 0.6}
                    y={MID}
                    width={bw - 1.2}
                    height={Math.max(scale(p.n_full), p.n_full > 0 ? 1 : 0)}
                    fill="#4c8dff"
                    opacity={isActive ? 1 : 0.75}
                  />
                </>
              )}
              <rect
                x={x}
                y={0}
                width={bw}
                height={H}
                fill="transparent"
                style={{ cursor: onSlotSelect ? "pointer" : "default" }}
                onMouseEnter={() => setHover(slot)}
                onClick={() => onSlotSelect?.(slot)}
              />
            </g>
          )
        })}

        {currentSlot != null && (
          <line
            x1={currentSlot * bw + bw / 2}
            y1={0}
            x2={currentSlot * bw + bw / 2}
            y2={H}
            stroke="#ffd400"
            strokeWidth={1.5}
          />
        )}
      </svg>

      <div className="mt-1 flex justify-between px-[1px]">
        {[0, 6, 12, 18, 24].map((h) => (
          <span key={h} className="num text-[10px] text-ink-faint">
            {String(h % 24).padStart(2, "0")}:00
          </span>
        ))}
      </div>
    </div>
  )
}

/** 把常態值畫成折線：dir = -1 往上（無車）、1 往下（無位） */
function linePath(
  base: Map<number, BaselinePoint>,
  slots: number,
  bw: number,
  mid: number,
  scale: (v: number) => number,
  key: "n_empty" | "n_full",
  dir: -1 | 1,
): string {
  const pts: string[] = []
  for (let s = 0; s < slots; s++) {
    const b = base.get(s)
    if (!b) continue
    const x = s * bw + bw / 2
    const y = mid + dir * scale(b[key])
    pts.push(`${pts.length === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`)
  }
  return pts.join(" ")
}
