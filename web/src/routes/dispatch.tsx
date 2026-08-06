import { useState } from "react"
import { useQuery } from "@tanstack/react-query"

import { StationDrawer } from "@/components/StationDrawer"
import { api } from "@/lib/api"
import { fmtClock } from "@/lib/status"

const HORIZONS = [30, 60, 120, 180] as const

/** 風險機率 → 顏色（沿用警示三級的色系）。 */
function riskColor(p: number | null | undefined): string {
  if (p == null) return "#8493ac"
  if (p >= 0.9) return "#ff5c5c"
  if (p >= 0.8) return "#ffb020"
  return "#8493ac"
}

export function DispatchPage() {
  const [horizon, setHorizon] = useState<number>(60)
  const [selected, setSelected] = useState<number | null>(null)

  const q = useQuery({
    queryKey: ["dispatch", horizon],
    queryFn: () => api.dispatch(horizon, 60),
    refetchInterval: 120_000,
  })

  const data = q.data
  const tasks = data?.tasks ?? []
  const mode = data?.mode ?? "unavailable"
  const meta = data?.meta ?? {}
  const paired = tasks.filter((t) => t.from_station != null).length

  return (
    <div className="relative flex h-full">
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="shrink-0 border-b border-line px-5 py-4">
          <p className="eyebrow">調度建議 · WP5</p>
          <h1 className="mt-1 text-[19px] font-semibold">接下來這一小時，車該往哪裡搬</h1>
          <p className="mt-1 max-w-[68ch] text-[12px] leading-relaxed text-ink-dim">
            模型預測 <b className="font-normal text-ink">{horizon} 分鐘後</b>會缺車的站，
            配上同時段可能滿位、可以出車的站，湊成一趟「收 N 台 → 補到那裡」。
            目標水位取安全帶兩端：補到 <span className="num">35%</span>、收到{" "}
            <span className="num">65%</span>，一趟車同時解掉兩個問題。
            風險門檻用驗證集上 F1 最佳的值（各時距不同），比規劃書的 70% 敏感，
            換到的是<b className="font-normal text-ink">來得及出車的前置時間</b>。
          </p>

          <div className="mt-3 flex flex-wrap items-center gap-2">
            {HORIZONS.map((h) => (
              <button
                key={h}
                type="button"
                onClick={() => setHorizon(h)}
                className={`rounded border px-2.5 py-1 text-[12px] transition-colors ${
                  horizon === h
                    ? "border-line bg-panel-2 text-ink"
                    : "border-line-soft text-ink-dim hover:text-ink"
                }`}
              >
                <span className="num">{h}</span> 分後
              </button>
            ))}

            <span className="ml-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-ink-faint">
              <span>
                任務 <span className="num text-ink">{tasks.length}</span>
              </span>
              <span>
                可配對出車站 <span className="num text-ink">{paired}</span>
              </span>
              {data?.total_move_bikes != null && (
                <span>
                  合計搬運 <span className="num text-ink">{data.total_move_bikes}</span> 台
                </span>
              )}
              {meta.base_ts && <span>預測基準 {fmtClock(meta.base_ts)}</span>}
            </span>
          </div>

          {mode === "rule" && (
            <p className="mt-2 rounded border border-line-soft bg-panel px-3 py-1.5 text-[12px] text-ink-dim">
              模型預測尚未就緒，目前顯示的是<b className="font-normal text-ink">規則型現況調度</b>
              （已經空掉的站）。排程產生預測後會自動切回預測模式。
            </p>
          )}
          {mode === "forecast" && meta.live_slot_ratio != null && meta.live_slot_ratio < 0.2 && (
            <p className="mt-2 rounded border border-line-soft bg-panel px-3 py-1.5 text-[12px] text-ink-dim">
              即時快照才剛開始累積（近 7 天只有{" "}
              <span className="num">{(meta.live_slot_ratio * 100).toFixed(1)}%</span>{" "}
              的時間格是即時資料），其餘由「同站、同星期幾、同時段的上一次實際觀測」暖機補上。
              資料累積越多，這個比例會自動上升。
            </p>
          )}
        </header>

        <div className="min-h-0 flex-1 overflow-auto">
          <table className="w-full text-[12px]">
            <thead className="sticky top-0 z-10 bg-void">
              <tr className="border-b border-line text-left">
                <Th right>搬運</Th>
                <Th>補到（預測缺車）</Th>
                <Th>行政區</Th>
                <Th right>現在可借</Th>
                <Th right>{horizon} 分後預測</Th>
                <Th right>缺車機率</Th>
                <Th>從這裡收（預測滿位）</Th>
                <Th right>可收</Th>
                <Th right>距離</Th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((t) => (
                <tr
                  key={`${t.to_station}-${t.from_station ?? "none"}`}
                  onClick={() => setSelected(t.to_station)}
                  className={`cursor-pointer border-b border-line-soft transition-colors hover:bg-panel ${
                    selected === t.to_station ? "bg-panel" : ""
                  }`}
                >
                  <td className="num px-4 py-1.5 text-right text-[15px] font-semibold text-ink">
                    {t.move_bikes ?? t.need_bikes}
                  </td>
                  <td className="px-4 py-1.5 text-ink">{t.to_name}</td>
                  <td className="px-4 py-1.5 text-ink-dim">{t.district}</td>
                  <td className="num px-4 py-1.5 text-right">{t.now_bikes}</td>
                  <td className="num px-4 py-1.5 text-right">
                    {t.to_pred_bikes != null ? (
                      <>
                        {t.to_pred_bikes}
                        <span className="text-ink-faint"> / {t.to_capacity}</span>
                      </>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="num px-4 py-1.5 text-right" style={{ color: riskColor(t.proba_empty) }}>
                    {t.proba_empty != null ? `${(t.proba_empty * 100).toFixed(0)}%` : "—"}
                  </td>
                  <td className="px-4 py-1.5">
                    {t.from_name ? (
                      <span className="text-ink-dim">
                        <span className="text-ink-faint">← </span>
                        {t.from_name}
                      </span>
                    ) : (
                      <span className="text-ink-faint">無鄰近滿位站，需由調度中心出車</span>
                    )}
                  </td>
                  <td className="num px-4 py-1.5 text-right text-ink-dim">
                    {t.spare_bikes ?? "—"}
                  </td>
                  <td className="num px-4 py-1.5 text-right text-ink-faint">
                    {t.distance_km != null ? `${t.distance_km.toFixed(2)} km` : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {tasks.length === 0 && !q.isLoading && (
            <p className="py-10 text-center text-xs text-ink-faint">
              {mode === "unavailable"
                ? "預測與警示資料都還沒就緒，排程跑完後這裡就會有任務。"
                : `${horizon} 分鐘內沒有站點達到預警門檻，暫時不需要調度。`}
            </p>
          )}
          {q.isLoading && (
            <p className="py-10 text-center text-xs text-ink-faint">擬定調度中…</p>
          )}
        </div>
      </div>

      <StationDrawer stationId={selected} onClose={() => setSelected(null)} />
    </div>
  )
}

function Th({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return (
    <th className={`eyebrow px-4 py-2 font-normal ${right ? "text-right" : "text-left"}`}>
      {children}
    </th>
  )
}
