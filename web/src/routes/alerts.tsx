import { useMemo, useState } from "react"
import { useQuery } from "@tanstack/react-query"

import { StationDrawer } from "@/components/StationDrawer"
import { api } from "@/lib/api"
import type { AlertLevel } from "@/lib/api"
import { KIND_LABEL, LEVEL, fmtDuration, fmtTime } from "@/lib/status"

const LEVELS: AlertLevel[] = ["critical", "warning", "notice"]

export function AlertsPage() {
  const [level, setLevel] = useState<AlertLevel | "all">("all")
  const [district, setDistrict] = useState<string>("all")
  const [selected, setSelected] = useState<number | null>(null)

  const alerts = useQuery({
    queryKey: ["alerts"],
    queryFn: api.alerts,
    refetchInterval: 60_000,
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
            分級規則直接對應命題痛點「系統不會主動通知機關」：
            可借或可還剩 2 台以內是<b className="font-normal text-ink">注意</b>；
            已空或已滿是<b className="font-normal text-ink">警戒</b>；
            持續 60 分鐘以上是<b className="font-normal text-ink">嚴重</b>。
            資料每 10 分鐘由排程重算。
          </p>

          <div className="mt-3 flex flex-wrap items-center gap-2">
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
        </div>
      </div>

      <StationDrawer stationId={selected} onClose={() => setSelected(null)} />
    </div>
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
