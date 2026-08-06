import { useQuery } from "@tanstack/react-query"
import ReactECharts from "echarts-for-react"
import { X } from "lucide-react"

import { api } from "@/lib/api"
import { STATUS, fmtTime } from "@/lib/status"

interface Props {
  stationId: number | null
  onClose: () => void
}

const DAYS = 7

export function StationDrawer({ stationId, onClose }: Props) {
  const detail = useQuery({
    queryKey: ["station", stationId],
    queryFn: () => api.station(stationId as number),
    enabled: stationId != null,
  })
  const history = useQuery({
    queryKey: ["station-history", stationId, DAYS],
    queryFn: () => api.stationHistory(stationId as number, DAYS),
    enabled: stationId != null,
  })

  if (stationId == null) return null

  const d = detail.data
  const st = d?.current?.status ? STATUS[d.current.status] : null
  const points = history.data?.points ?? []

  return (
    <aside
      className="absolute top-0 right-0 z-20 flex h-full w-full max-w-[380px] flex-col border-l border-line bg-panel/95 backdrop-blur-sm"
      aria-label="站點詳情"
    >
      <header className="flex shrink-0 items-start justify-between gap-3 border-b border-line px-4 py-3">
        <div className="min-w-0">
          <p className="eyebrow">站點詳情</p>
          <h2 className="mt-0.5 truncate text-[15px] leading-snug font-semibold">
            {d?.name ?? "載入中…"}
          </h2>
          <p className="num mt-0.5 text-[11px] text-ink-dim">
            {d?.district ?? ""} · 車柱 {d?.capacity_docks ?? "—"}
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded p-1 text-ink-faint transition-colors hover:bg-panel-2 hover:text-ink"
          aria-label="關閉站點詳情"
        >
          <X size={16} />
        </button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
        {d?.current && (
          <section>
            <div className="flex items-center gap-2">
              <span
                className="h-2 w-2 rounded-full"
                style={{ background: st?.color }}
              />
              <span className="text-[13px]" style={{ color: st?.color }}>
                {st?.label}
              </span>
              <span className="num ml-auto text-[11px] text-ink-faint">
                {fmtTime(d.current.ts)}
              </span>
            </div>
            <div className="mt-2 grid grid-cols-2 gap-2">
              <Stat label="可借車輛" value={d.current.bikes} accent="#21d0a5" />
              <Stat label="可還空位" value={d.current.docks_avail} accent="#4c8dff" />
            </div>
          </section>
        )}

        <section className="mt-5">
          <p className="eyebrow mb-1">近 {DAYS} 天可借車數</p>
          {history.isLoading ? (
            <p className="py-8 text-center text-xs text-ink-faint">載入中…</p>
          ) : points.length === 0 ? (
            <p className="py-8 text-center text-xs text-ink-faint">這段期間沒有紀錄。</p>
          ) : (
            <ReactECharts
              style={{ height: 180 }}
              opts={{ renderer: "svg" }}
              option={{
                backgroundColor: "transparent",
                grid: { left: 30, right: 8, top: 12, bottom: 22 },
                tooltip: {
                  trigger: "axis",
                  backgroundColor: "#121a2a",
                  borderColor: "#253148",
                  textStyle: { color: "#e6edf8", fontSize: 11 },
                },
                xAxis: {
                  type: "time",
                  axisLine: { lineStyle: { color: "#253148" } },
                  axisLabel: { color: "#56637a", fontSize: 10 },
                  splitLine: { show: false },
                },
                yAxis: {
                  type: "value",
                  min: 0,
                  axisLabel: { color: "#56637a", fontSize: 10 },
                  splitLine: { lineStyle: { color: "#1b2537" } },
                },
                series: [
                  {
                    type: "line",
                    name: "可借車數",
                    showSymbol: false,
                    smooth: false,
                    lineStyle: { width: 1.2, color: "#21d0a5" },
                    areaStyle: { color: "rgba(33,208,165,0.10)" },
                    data: points.map((p) => [p.ts, p.bikes]),
                  },
                ],
              }}
            />
          )}
        </section>

        {d?.stats && (
          <section className="mt-5">
            <p className="eyebrow mb-2">歷史表現（全期）</p>
            <dl className="space-y-1.5 text-[12px]">
              <Row label="無車可借時間占比" value={pct(d.stats.empty_rate)} color="#ff5c5c" />
              <Row label="無位可還時間占比" value={pct(d.stats.full_rate)} color="#4c8dff" />
              <Row label="平均可借車數" value={d.stats.bikes_mean?.toFixed(1) ?? "—"} />
              <Row label="平均滿載率" value={pct(d.stats.occ_rate)} />
              <Row
                label="納入統計的快照"
                value={d.stats.n_snapshots?.toLocaleString() ?? "—"}
              />
            </dl>
          </section>
        )}
      </div>
    </aside>
  )
}

function pct(v: number | null | undefined): string {
  return v == null ? "—" : `${(v * 100).toFixed(1)}%`
}

function Stat({
  label,
  value,
  accent,
}: {
  label: string
  value: number | null
  accent: string
}) {
  return (
    <div className="rounded border border-line bg-void/40 px-3 py-2">
      <p className="eyebrow">{label}</p>
      <p className="num mt-0.5 text-[22px] leading-none" style={{ color: accent }}>
        {value ?? "—"}
      </p>
    </div>
  )
}

function Row({
  label,
  value,
  color,
}: {
  label: string
  value: string
  color?: string
}) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-line-soft pb-1.5">
      <dt className="text-ink-dim">{label}</dt>
      <dd className="num" style={{ color: color ?? "var(--ink)" }}>
        {value}
      </dd>
    </div>
  )
}
