import { useState } from "react"
import { useQuery } from "@tanstack/react-query"

import { AlertPanel } from "@/components/AlertPanel"
import { PulseRibbon } from "@/components/PulseRibbon"
import { StationDrawer } from "@/components/StationDrawer"
import { StationMap } from "@/components/StationMap"
import { api } from "@/lib/api"
import { STATUS } from "@/lib/status"

const REFRESH = 60_000

export function IndexPage() {
  const [selected, setSelected] = useState<number | null>(null)

  const stations = useQuery({
    queryKey: ["stations"],
    queryFn: api.stations,
    refetchInterval: REFRESH,
  })
  const alerts = useQuery({
    queryKey: ["alerts"],
    queryFn: api.alerts,
    refetchInterval: REFRESH,
  })
  const overview = useQuery({
    queryKey: ["overview"],
    queryFn: api.overview,
    refetchInterval: REFRESH,
  })
  const pulse = useQuery({ queryKey: ["pulse"], queryFn: () => api.pulse() })

  const now = overview.data?.now
  const asOf = stations.data?.as_of ? new Date(stations.data.as_of) : null
  const currentSlot = asOf
    ? asOf.getHours() * 2 + (asOf.getMinutes() >= 30 ? 1 : 0)
    : null

  return (
    <div className="flex h-full">
      {/* 左欄：現況數字 + 待處理站點 */}
      <div className="flex w-[300px] shrink-0 flex-col border-r border-line">
        <section className="shrink-0 border-b border-line px-3 py-3">
          <p className="eyebrow mb-2">此刻全市</p>
          <div className="grid grid-cols-2 gap-2">
            <Kpi label="無車可借" value={now?.n_empty} color="#ff5c5c" hint="站上一台車都沒有" />
            <Kpi label="無位可還" value={now?.n_full} color="#4c8dff" hint="車柱全滿，還不了車" />
            <Kpi label="瀕臨空滿" value={now?.n_risk} color="#ffb020" hint="可借或可還剩 2 台以內" />
            <Kpi label="營運站數" value={now?.n_stations} color="#8493ac" hint="扣除長期未營運站" />
          </div>
          <p className="num mt-2 text-[11px] text-ink-faint">
            全市車輛 {now?.bikes?.toLocaleString() ?? "—"} / 車柱{" "}
            {now?.docks_total?.toLocaleString() ?? "—"}
            {now?.occ_rate != null && ` · 滿載率 ${(now.occ_rate * 100).toFixed(1)}%`}
          </p>
        </section>

        <section className="flex min-h-0 flex-1 flex-col pt-3">
          <p className="eyebrow mb-2 px-3">待處理站點</p>
          {alerts.isLoading ? (
            <p className="px-3 text-xs text-ink-faint">載入中…</p>
          ) : (
            <AlertPanel
              alerts={alerts.data?.alerts ?? []}
              selectedId={selected}
              onSelect={setSelected}
            />
          )}
        </section>
      </div>

      {/* 主區：地圖 + 脈搏帶 */}
      <div className="relative flex min-w-0 flex-1 flex-col">
        <div className="relative min-h-0 flex-1">
          <StationMap
            stations={stations.data?.stations ?? []}
            selectedId={selected}
            onSelect={setSelected}
          />
          <Legend />
          <StationDrawer stationId={selected} onClose={() => setSelected(null)} />
        </div>

        <div className="shrink-0 border-t border-line px-4 py-2">
          <PulseRibbon
            points={pulse.data?.points ?? []}
            currentSlot={currentSlot}
            label={`全市空滿脈搏 · ${pulse.data?.date ?? ""}`}
          />
        </div>
      </div>
    </div>
  )
}

function Kpi({
  label,
  value,
  color,
  hint,
}: {
  label: string
  value?: number
  color: string
  hint: string
}) {
  return (
    <div className="rounded border border-line bg-panel px-2.5 py-2" title={hint}>
      <p className="eyebrow">{label}</p>
      <p className="num mt-0.5 text-[24px] leading-none" style={{ color }}>
        {value?.toLocaleString() ?? "—"}
      </p>
    </div>
  )
}

const LEGEND_ITEMS = ["empty", "full", "near_empty", "normal", "offline"] as const

function Legend() {
  return (
    <div className="absolute bottom-3 left-3 z-10 rounded border border-line bg-panel/90 px-2.5 py-2 backdrop-blur-sm">
      <p className="eyebrow mb-1.5">站點狀態</p>
      <ul className="space-y-1">
        {LEGEND_ITEMS.map((k) => (
          <li key={k} className="flex items-center gap-2 text-[11px] text-ink-dim">
            <span
              className="h-2 w-2 rounded-full"
              style={{ background: STATUS[k].color }}
            />
            {k === "near_empty" ? "將空／將滿" : STATUS[k].label}
          </li>
        ))}
      </ul>
    </div>
  )
}
