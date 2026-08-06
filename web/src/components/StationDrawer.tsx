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
  const forecast = useQuery({
    queryKey: ["station-forecast", stationId],
    queryFn: () => api.forecastStation(stationId as number),
    enabled: stationId != null,
    refetchInterval: 120_000,
  })

  if (stationId == null) return null

  const d = detail.data
  const st = d?.current?.status ? STATUS[d.current.status] : null
  const points = history.data?.points ?? []
  const fc = forecast.data?.forecast ?? []
  // 預測折線：從基準時刻的實際車數出發，往後接 4 個時距的預測值
  const base = fc[0]?.base_ts
  const at = (h: number) => new Date(new Date(base).getTime() + h * 60_000).toISOString()
  const predPoints = base
    ? [
        [base, fc[0].now_bikes] as [string, number],
        ...fc.map((f) => [at(f.horizon), f.pred_bikes] as [string, number]),
      ]
    : []
  // 10%–90% 分位數區間：ECharts 用「下界 + 帶寬」兩條 stack 起來畫成帶
  const hasBand = base != null && fc.some((f) => f.pred_bikes_hi != null)
  const loPoints = hasBand
    ? [
        [base, fc[0].now_bikes] as [string, number],
        ...fc.map((f) => [at(f.horizon), f.pred_bikes_lo ?? f.pred_bikes] as [string, number]),
      ]
    : []
  const bandPoints = hasBand
    ? [
        [base, 0] as [string, number],
        ...fc.map(
          (f) =>
            [
              at(f.horizon),
              Math.max((f.pred_bikes_hi ?? f.pred_bikes) - (f.pred_bikes_lo ?? f.pred_bikes), 0),
            ] as [string, number],
        ),
      ]
    : []

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
                  ...(hasBand
                    ? [
                        {
                          type: "line",
                          name: "區間下界",
                          stack: "band",
                          symbol: "none",
                          silent: true,
                          lineStyle: { opacity: 0 },
                          tooltip: { show: false },
                          data: loPoints,
                        },
                        {
                          type: "line",
                          name: "預測區間 10–90%",
                          stack: "band",
                          symbol: "none",
                          silent: true,
                          lineStyle: { opacity: 0 },
                          areaStyle: { color: "rgba(192,132,252,0.18)" },
                          data: bandPoints,
                        },
                      ]
                    : []),
                  {
                    type: "line",
                    name: "模型預測",
                    showSymbol: true,
                    symbolSize: 4,
                    smooth: false,
                    lineStyle: { width: 1.2, color: "#c084fc", type: "dashed" },
                    itemStyle: { color: "#c084fc" },
                    data: predPoints,
                    z: 5,
                  },
                ],
              }}
            />
          )}
        </section>

        {fc.length > 0 && (
          <section className="mt-5">
            <p className="eyebrow mb-2">模型預測（LightGBM）</p>
            <div className="grid grid-cols-4 gap-1.5">
              {fc.map((f) => {
                const risk = Math.max(f.proba_empty, f.proba_full)
                const kind = f.proba_empty >= f.proba_full ? "空" : "滿"
                const alert = f.alert_empty || f.alert_full
                return (
                  <div
                    key={f.horizon}
                    className="rounded border bg-void/40 px-2 py-1.5"
                    style={{ borderColor: alert ? "#ff5c5c55" : "var(--line)" }}
                  >
                    <p className="eyebrow">+{f.horizon}分</p>
                    <p className="num mt-0.5 text-[17px] leading-none text-ink">{f.pred_bikes}</p>
                    {f.pred_bikes_hi != null && f.pred_bikes_lo != null && (
                      <p className="num mt-0.5 text-[10px] text-ink-faint">
                        {f.pred_bikes_lo}–{f.pred_bikes_hi}
                      </p>
                    )}
                    <p
                      className="num mt-1 text-[10px]"
                      style={{ color: alert ? "#ff5c5c" : "var(--ink-faint)" }}
                    >
                      {kind} {(risk * 100).toFixed(0)}%
                    </p>
                  </div>
                )
              })}
            </div>
            <p className="mt-1.5 text-[11px] leading-relaxed text-ink-faint">
              大字是預測的<b className="font-normal text-ink-dim">可借車數</b>，
              底下小字是 10–90% 分位數區間（模型認為八成機會落在這個範圍），
              最下面是該時距「無車／無位」的機率。
            </p>
          </section>
        )}

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
