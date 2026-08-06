import { useMemo, useState } from "react"
import { useQuery } from "@tanstack/react-query"

import { StationDrawer } from "@/components/StationDrawer"
import { api } from "@/lib/api"
import type { AlertLevel, ForecastAlert } from "@/lib/api"
import { KIND_LABEL, LEVEL, fmtClock, fmtDuration, fmtTime } from "@/lib/status"

const LEVELS: AlertLevel[] = ["critical", "warning", "notice"]
const FC_HORIZONS = [30, 60, 120, 180] as const

export function AlertsPage() {
  const [level, setLevel] = useState<AlertLevel | "all">("all")
  const [district, setDistrict] = useState<string>("all")
  const [selected, setSelected] = useState<number | null>(null)
  const [mode, setMode] = useState<"now" | "forecast">("now")
  const [horizon, setHorizon] = useState<number>(60)

  const alerts = useQuery({
    queryKey: ["alerts"],
    queryFn: api.alerts,
    refetchInterval: 60_000,
  })
  const fcAlerts = useQuery({
    queryKey: ["forecast-alerts", horizon],
    queryFn: () => api.forecastAlerts(horizon),
    refetchInterval: 120_000,
    enabled: mode === "forecast",
  })

  const rows = alerts.data?.alerts ?? []
  const districts = useMemo(
    () => [...new Set(rows.map((a) => a.district).filter(Boolean))].sort() as string[],
    [rows],
  )
  const counts = useMemo(() => {
    const c: Record<string, number> = { critical: 0, warning: 0, notice: 0 }
    for (const a of rows) c[a.level] = (c[a.level] ?? 0) + 1
    return c
  }, [rows])

  const shown = rows.filter(
    (a) =>
      (level === "all" || a.level === level) &&
      (district === "all" || a.district === district),
  )

  return (
    <div className="relative flex h-full">
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="shrink-0 border-b border-line px-5 py-4">
          <p className="eyebrow">警示引擎 · WP4</p>
          <h1 className="mt-1 text-[19px] font-semibold">現在有哪些站需要處理</h1>
          <p className="mt-1 max-w-[62ch] text-[12px] leading-relaxed text-ink-dim">
            {mode === "now" ? (
              <>
                分級規則直接對應命題痛點「系統不會主動通知機關」：
                可借或可還剩 2 台以內是<b className="font-normal text-ink">注意</b>；
                已空或已滿是<b className="font-normal text-ink">警戒</b>；
                持續 60 分鐘以上是<b className="font-normal text-ink">嚴重</b>。
                資料每 10 分鐘由排程重算。
              </>
            ) : (
              <>
                規則型看的是<b className="font-normal text-ink">已經發生</b>的事，
                這裡看的是<b className="font-normal text-ink">還沒發生</b>的事：
                LightGBM 判定該站 {horizon} 分鐘內可能無車或無位就進榜。
                門檻取<b className="font-normal text-ink">驗證集上 F1 最佳的值</b>（各時距不同，約 10–30%），
                而不是規劃書那個偏保守的 70%——70% 幾乎只在事情快發生時才會亮，來不及派車。
                排程每 30 分鐘重算一次。
              </>
            )}
          </p>

          <div className="mt-3 flex items-center gap-1.5">
            {([
              ["now", "現況"],
              ["forecast", "預測"],
            ] as const).map(([m, label]) => (
              <button
                key={m}
                type="button"
                onClick={() => setMode(m)}
                className={`rounded border px-2.5 py-1 text-[12px] transition-colors ${
                  mode === m
                    ? "border-line bg-panel-2 text-ink"
                    : "border-line-soft text-ink-dim hover:text-ink"
                }`}
              >
                {label}
              </button>
            ))}
            {mode === "forecast" && (
              <>
                <span className="ml-1 text-[11px] text-ink-faint">時距</span>
                {FC_HORIZONS.map((h) => (
                  <button
                    key={h}
                    type="button"
                    onClick={() => setHorizon(h)}
                    className={`rounded border px-2 py-0.5 text-[12px] transition-colors ${
                      horizon === h
                        ? "border-line bg-panel-2 text-ink"
                        : "border-line-soft text-ink-dim hover:text-ink"
                    }`}
                  >
                    <span className="num">{h}</span>
                  </button>
                ))}
                {fcAlerts.data?.meta?.base_ts && (
                  <span className="ml-2 text-[11px] text-ink-faint">
                    預測基準 {fmtClock(fcAlerts.data.meta.base_ts)}
                  </span>
                )}
              </>
            )}
          </div>

          <div
            className={`mt-3 flex flex-wrap items-center gap-2 ${mode === "forecast" ? "hidden" : ""}`}
          >
            {(["all", ...LEVELS] as const).map((lv) => (
              <button
                key={lv}
                type="button"
                onClick={() => setLevel(lv)}
                className={`flex items-center gap-1.5 rounded border px-2.5 py-1 text-[12px] transition-colors ${
                  level === lv
                    ? "border-line bg-panel-2 text-ink"
                    : "border-line-soft text-ink-dim hover:text-ink"
                }`}
              >
                {lv !== "all" && (
                  <span
                    className="h-1.5 w-1.5 rounded-full"
                    style={{ background: LEVEL[lv].color }}
                  />
                )}
                {lv === "all" ? "全部" : LEVEL[lv].label}
                <span className="num text-ink-faint">
                  {lv === "all" ? rows.length : (counts[lv] ?? 0)}
                </span>
              </button>
            ))}

            <select
              value={district}
              onChange={(e) => setDistrict(e.target.value)}
              className="ml-2 rounded border border-line-soft bg-panel px-2 py-1 text-[12px] text-ink-dim"
            >
              <option value="all">全部行政區</option>
              {districts.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
          </div>
        </header>

        <div className="min-h-0 flex-1 overflow-auto">
          {mode === "forecast" ? (
            <ForecastTable
              rows={fcAlerts.data?.alerts ?? []}
              loading={fcAlerts.isLoading}
              horizon={horizon}
              selected={selected}
              onSelect={setSelected}
            />
          ) : (
          <>
          <table className="w-full text-[12px]">
            <thead className="sticky top-0 z-10 bg-void">
              <tr className="border-b border-line text-left">
                <Th>分級</Th>
                <Th>站點</Th>
                <Th>行政區</Th>
                <Th>狀況</Th>
                <Th right>已持續</Th>
                <Th right>可借</Th>
                <Th right>可還</Th>
                <Th right>車柱</Th>
                <Th right>資料時間</Th>
              </tr>
            </thead>
            <tbody>
              {shown.map((a) => (
                <tr
                  key={`${a.station_id}-${a.kind}`}
                  onClick={() => setSelected(a.station_id)}
                  className={`cursor-pointer border-b border-line-soft transition-colors hover:bg-panel ${
                    selected === a.station_id ? "bg-panel" : ""
                  }`}
                >
                  <td className="px-4 py-1.5">
                    <span
                      className="inline-flex items-center gap-1.5"
                      style={{ color: LEVEL[a.level].color }}
                    >
                      <span
                        className="h-1.5 w-1.5 rounded-full"
                        style={{ background: LEVEL[a.level].color }}
                      />
                      {LEVEL[a.level].label}
                    </span>
                  </td>
                  <td className="px-4 py-1.5 text-ink">{a.name}</td>
                  <td className="px-4 py-1.5 text-ink-dim">{a.district}</td>
                  <td className="px-4 py-1.5 text-ink-dim">{KIND_LABEL[a.kind]}</td>
                  <td className="num px-4 py-1.5 text-right text-ink">
                    {a.kind === "empty" || a.kind === "full"
                      ? fmtDuration(a.duration_min, a.duration_capped)
                      : "—"}
                  </td>
                  <td className="num px-4 py-1.5 text-right">{a.bikes}</td>
                  <td className="num px-4 py-1.5 text-right">{a.docks_avail}</td>
                  <td className="num px-4 py-1.5 text-right text-ink-faint">
                    {a.docks_total}
                  </td>
                  <td className="num px-4 py-1.5 text-right text-ink-faint">
                    {fmtTime(a.ts)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {shown.length === 0 && !alerts.isLoading && (
            <p className="py-10 text-center text-xs text-ink-faint">
              這個條件下目前沒有站點需要處理。
            </p>
          )}
          </>
          )}
        </div>
      </div>

      <StationDrawer stationId={selected} onClose={() => setSelected(null)} />
    </div>
  )
}

function ForecastTable({
  rows,
  loading,
  horizon,
  selected,
  onSelect,
}: {
  rows: ForecastAlert[]
  loading: boolean
  horizon: number
  selected: number | null
  onSelect: (id: number) => void
}) {
  if (loading) {
    return <p className="py-10 text-center text-xs text-ink-faint">推論結果載入中…</p>
  }
  if (rows.length === 0) {
    return (
      <p className="py-10 text-center text-xs text-ink-faint">
        {horizon} 分鐘內沒有站點達到 70% 預警門檻，或排程還沒產生第一份預測。
      </p>
    )
  }
  return (
    <table className="w-full text-[12px]">
      <thead className="sticky top-0 z-10 bg-void">
        <tr className="border-b border-line text-left">
          <Th>預警</Th>
          <Th>站點</Th>
          <Th>行政區</Th>
          <Th right>機率</Th>
          <Th right>現在可借</Th>
          <Th right>{horizon} 分後預測可借</Th>
          <Th right>車柱</Th>
          <Th right>預測基準</Th>
        </tr>
      </thead>
      <tbody>
        {rows.map((a) => {
          const color = a.proba >= 0.9 ? "#ff5c5c" : a.proba >= 0.8 ? "#ffb020" : "#c084fc"
          return (
            <tr
              key={`${a.station_id}-${a.kind}`}
              onClick={() => onSelect(a.station_id)}
              className={`cursor-pointer border-b border-line-soft transition-colors hover:bg-panel ${
                selected === a.station_id ? "bg-panel" : ""
              }`}
            >
              <td className="px-4 py-1.5">
                <span className="inline-flex items-center gap-1.5" style={{ color }}>
                  <span className="h-1.5 w-1.5 rounded-full" style={{ background: color }} />
                  {a.kind === "empty" ? "可能無車" : "可能滿位"}
                </span>
              </td>
              <td className="px-4 py-1.5 text-ink">{a.name}</td>
              <td className="px-4 py-1.5 text-ink-dim">{a.district}</td>
              <td className="num px-4 py-1.5 text-right" style={{ color }}>
                {(a.proba * 100).toFixed(0)}%
              </td>
              <td className="num px-4 py-1.5 text-right">{a.now_bikes}</td>
              <td className="num px-4 py-1.5 text-right text-ink">{a.pred_bikes}</td>
              <td className="num px-4 py-1.5 text-right text-ink-faint">{a.docks_total}</td>
              <td className="num px-4 py-1.5 text-right text-ink-faint">{fmtTime(a.base_ts)}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

function Th({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return (
    <th
      className={`eyebrow px-4 py-2 font-normal ${right ? "text-right" : "text-left"}`}
    >
      {children}
    </th>
  )
}
