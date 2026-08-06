import { useMemo, useState } from "react"
import { useQuery } from "@tanstack/react-query"

import { api } from "@/lib/api"
import { WEEKDAY, slotLabel } from "@/lib/status"

export function DistrictsPage() {
  const [district, setDistrict] = useState<string | null>(null)

  const districts = useQuery({
    queryKey: ["districts"],
    queryFn: api.districts,
    refetchInterval: 60_000,
  })
  const hourly = useQuery({
    queryKey: ["hourly-all", district],
    queryFn: () => fetchHourly(district),
  })
  const worst = useQuery({
    queryKey: ["worst"],
    queryFn: () => api.worst("empty", 12),
  })

  const rows = districts.data?.districts ?? []
  const maxProblem = Math.max(1, ...rows.map((r) => r.n_empty + r.n_full))

  return (
    <div className="h-full overflow-auto">
      <header className="border-b border-line px-5 py-4">
        <p className="eyebrow">區域分析 · WP1</p>
        <h1 className="mt-1 text-[19px] font-semibold">哪一區、哪個時段最容易壞</h1>
        <p className="mt-1 max-w-[68ch] text-[12px] leading-relaxed text-ink-dim">
          左邊是此刻各行政區的供需狀況，右邊是六個月歷史累積出的「星期 × 半小時」
          無車型態。通勤雙峰與週末型態的差異，決定調度策略該往哪個方向走。
        </p>
      </header>

      <div className="grid gap-5 p-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
        <section>
          <p className="eyebrow mb-2">
            此刻各行政區{district ? ` · 已選 ${district}` : "（點列可篩右側熱力圖）"}
          </p>
          <div className="overflow-x-auto rounded border border-line">
            <table className="w-full text-[12px]">
              <thead>
                <tr className="border-b border-line bg-panel text-left">
                  <Th>行政區</Th>
                  <Th right>站數</Th>
                  <Th right>車輛</Th>
                  <Th right>滿載率</Th>
                  <Th right>無車</Th>
                  <Th right>無位</Th>
                  <Th>問題站占比</Th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const problem = r.n_empty + r.n_full
                  const active = district === r.district
                  return (
                    <tr
                      key={r.district}
                      onClick={() => setDistrict(active ? null : r.district)}
                      className={`cursor-pointer border-b border-line-soft transition-colors hover:bg-panel ${
                        active ? "bg-panel" : ""
                      }`}
                    >
                      <td className="px-3 py-1.5 text-ink">{r.district}</td>
                      <td className="num px-3 py-1.5 text-right text-ink-dim">
                        {r.n_stations}
                      </td>
                      <td className="num px-3 py-1.5 text-right text-ink-dim">
                        {r.bikes?.toLocaleString()}
                      </td>
                      <td className="num px-3 py-1.5 text-right">
                        {r.occ_rate != null ? `${(r.occ_rate * 100).toFixed(0)}%` : "—"}
                      </td>
                      <td className="num px-3 py-1.5 text-right text-st-empty">
                        {r.n_empty}
                      </td>
                      <td className="num px-3 py-1.5 text-right text-st-full">
                        {r.n_full}
                      </td>
                      <td className="px-3 py-1.5">
                        <div className="flex h-1.5 w-full min-w-[60px] overflow-hidden rounded-full bg-line-soft">
                          <div
                            style={{
                              width: `${(problem / maxProblem) * 100}%`,
                              background:
                                r.n_empty >= r.n_full ? "#ff5c5c" : "#4c8dff",
                            }}
                          />
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </section>

        <div className="space-y-5">
          <section>
            <p className="eyebrow mb-2">
              歷史無車型態 · 星期 × 半小時{district ? ` · ${district}` : " · 全市"}
            </p>
            <Heatmap rows={hourly.data ?? []} loading={hourly.isLoading} />
          </section>

          <section>
            <p className="eyebrow mb-2">全期最常無車的站</p>
            <ol className="rounded border border-line">
              {(worst.data?.rows ?? []).map((r, i) => (
                <li
                  key={r.station_id}
                  className="flex items-center gap-3 border-b border-line-soft px-3 py-1.5 text-[12px] last:border-b-0"
                >
                  <span className="num w-5 text-right text-ink-faint">{i + 1}</span>
                  <span className="min-w-0 flex-1 truncate text-ink">{r.name}</span>
                  <span className="w-16 shrink-0 text-right text-[11px] text-ink-faint">
                    {r.district}
                  </span>
                  <span className="num w-14 shrink-0 text-right text-st-empty">
                    {(r.empty_rate * 100).toFixed(1)}%
                  </span>
                </li>
              ))}
            </ol>
            <p className="mt-1.5 text-[11px] text-ink-faint">
              百分比＝六個月內「站上一台車都沒有」的時間占比。
            </p>
          </section>
        </div>
      </div>
    </div>
  )
}

async function fetchHourly(district: string | null) {
  const qs = district ? `?district=${encodeURIComponent(district)}` : ""
  const res = await fetch(`/api/stats/hourly${qs}`)
  if (!res.ok) throw new Error(String(res.status))
  const json = (await res.json()) as { rows: Array<{ isodow: number; slot: number; empty_rate: number }> }
  return json.rows
}

/** 7 × 48 的無車率熱力網格；顏色越紅代表該時段越常沒車可借。 */
function Heatmap({
  rows,
  loading,
}: {
  rows: Array<{ isodow: number; slot: number; empty_rate: number }>
  loading: boolean
}) {
  const [hover, setHover] = useState<{ d: number; s: number; v: number } | null>(null)

  const { grid, max } = useMemo(() => {
    const grid = new Map<string, number>()
    let max = 0.001
    for (const r of rows) {
      grid.set(`${r.isodow}-${r.slot}`, r.empty_rate)
      if (r.empty_rate > max) max = r.empty_rate
    }
    return { grid, max }
  }, [rows])

  if (loading) {
    return <p className="py-10 text-center text-xs text-ink-faint">載入中…</p>
  }

  const CELL = 13
  const GAP = 1
  const LEFT = 22
  const w = LEFT + 48 * (CELL + GAP)
  const h = 7 * (CELL + GAP) + 16

  return (
    <div className="overflow-x-auto rounded border border-line bg-panel p-3">
      <svg viewBox={`0 0 ${w} ${h}`} className="w-full min-w-[560px]">
        {Array.from({ length: 7 }, (_, i) => {
          const dow = i + 1
          return (
            <g key={dow}>
              <text
                x={0}
                y={i * (CELL + GAP) + CELL - 2}
                fill="#56637a"
                fontSize={9}
                fontFamily="ui-monospace, monospace"
              >
                {WEEKDAY[i]}
              </text>
              {Array.from({ length: 48 }, (_, slot) => {
                const v = grid.get(`${dow}-${slot}`) ?? 0
                const t = Math.min(1, v / max)
                return (
                  <rect
                    key={slot}
                    x={LEFT + slot * (CELL + GAP)}
                    y={i * (CELL + GAP)}
                    width={CELL}
                    height={CELL}
                    rx={1.5}
                    fill={heat(t)}
                    onMouseEnter={() => setHover({ d: dow, s: slot, v })}
                    onMouseLeave={() => setHover(null)}
                  />
                )
              })}
            </g>
          )
        })}
        {[0, 6, 12, 18].map((hh) => (
          <text
            key={hh}
            x={LEFT + hh * 2 * (CELL + GAP)}
            y={h - 3}
            fill="#56637a"
            fontSize={9}
            fontFamily="ui-monospace, monospace"
          >
            {String(hh).padStart(2, "0")}:00
          </text>
        ))}
      </svg>
      <p className="num mt-1 text-[11px] text-ink-dim">
        {hover ? (
          <>
            星期{WEEKDAY[hover.d - 1]} {slotLabel(hover.s)} ·{" "}
            <span className="text-st-empty">無車率 {(hover.v * 100).toFixed(1)}%</span>
          </>
        ) : (
          <span className="text-ink-faint">滑過格子看該時段的無車率</span>
        )}
      </p>
    </div>
  )
}

/** 深藍 → 紅的單向色階；0 是背景色，避免空值看起來像有資料 */
function heat(t: number): string {
  if (t <= 0.001) return "#161f31"
  const stops: Array<[number, [number, number, number]]> = [
    [0, [22, 31, 49]],
    [0.35, [64, 66, 110]],
    [0.7, [186, 84, 92]],
    [1, [255, 92, 92]],
  ]
  for (let i = 1; i < stops.length; i++) {
    if (t <= stops[i][0]) {
      const [t0, c0] = stops[i - 1]
      const [t1, c1] = stops[i]
      const k = (t - t0) / (t1 - t0)
      const c = c0.map((v, j) => Math.round(v + (c1[j] - v) * k))
      return `rgb(${c[0]},${c[1]},${c[2]})`
    }
  }
  return "#ff5c5c"
}

function Th({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return (
    <th
      className={`eyebrow px-3 py-2 font-normal ${right ? "text-right" : "text-left"}`}
    >
      {children}
    </th>
  )
}
