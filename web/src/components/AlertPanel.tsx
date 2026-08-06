import { useMemo, useState } from "react"

import type { Alert, AlertLevel } from "@/lib/api"
import { KIND_LABEL, LEVEL, fmtDuration } from "@/lib/status"

interface Props {
  alerts: Alert[]
  selectedId?: number | null
  onSelect?: (id: number) => void
  compact?: boolean
}

const ORDER: AlertLevel[] = ["critical", "warning", "notice"]

export function AlertPanel({ alerts, selectedId, onSelect, compact }: Props) {
  const [filter, setFilter] = useState<AlertLevel | "all">("all")

  const counts = useMemo(() => {
    const c: Record<string, number> = { critical: 0, warning: 0, notice: 0 }
    for (const a of alerts) c[a.level] = (c[a.level] ?? 0) + 1
    return c
  }, [alerts])

  const shown = useMemo(
    () => (filter === "all" ? alerts : alerts.filter((a) => a.level === filter)),
    [alerts, filter],
  )

  return (
    <div className="flex min-h-0 flex-col">
      <div className="flex shrink-0 gap-1 px-3 pb-2">
        <FilterChip
          active={filter === "all"}
          onClick={() => setFilter("all")}
          label="全部"
          count={alerts.length}
        />
        {ORDER.map((lv) => (
          <FilterChip
            key={lv}
            active={filter === lv}
            onClick={() => setFilter(lv)}
            label={LEVEL[lv].label}
            count={counts[lv] ?? 0}
            color={LEVEL[lv].color}
          />
        ))}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {shown.length === 0 ? (
          <p className="px-3 py-6 text-center text-xs text-ink-faint">
            這個分級目前沒有站點需要處理。
          </p>
        ) : (
          <ul>
            {shown.map((a) => (
              <li key={`${a.station_id}-${a.kind}`}>
                <button
                  type="button"
                  onClick={() => onSelect?.(a.station_id)}
                  className={`flex w-full items-start gap-2.5 border-l-2 px-3 py-2 text-left transition-colors hover:bg-panel-2 ${
                    selectedId === a.station_id ? "bg-panel-2" : ""
                  }`}
                  style={{ borderLeftColor: LEVEL[a.level].color }}
                >
                  <span
                    className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full"
                    style={{ background: LEVEL[a.level].color }}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-baseline justify-between gap-2">
                      <span className="truncate text-[13px] leading-tight text-ink">
                        {a.name}
                      </span>
                      <span className="num shrink-0 text-[11px] text-ink-faint">
                        {a.district}
                      </span>
                    </span>
                    <span className="mt-0.5 flex items-baseline gap-2 text-[11px]">
                      <span style={{ color: LEVEL[a.level].color }}>
                        {KIND_LABEL[a.kind]}
                      </span>
                      {a.kind === "empty" || a.kind === "full" ? (
                        <span className="num text-ink-dim">
                          {fmtDuration(a.duration_min, a.duration_capped)}
                        </span>
                      ) : null}
                      {!compact && (
                        <span className="num ml-auto text-ink-faint">
                          {a.bikes}/{a.docks_total}
                        </span>
                      )}
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}

function FilterChip({
  active,
  onClick,
  label,
  count,
  color,
}: {
  active: boolean
  onClick: () => void
  label: string
  count: number
  color?: string
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex items-center gap-1.5 rounded border px-2 py-1 text-[11px] transition-colors ${
        active
          ? "border-line bg-panel-2 text-ink"
          : "border-transparent text-ink-dim hover:text-ink"
      }`}
    >
      {color && (
        <span className="h-1.5 w-1.5 rounded-full" style={{ background: color }} />
      )}
      {label}
      <span className="num text-ink-faint">{count}</span>
    </button>
  )
}
