import { Link, Outlet, useRouterState } from "@tanstack/react-router"
import { useQuery } from "@tanstack/react-query"

import { api } from "@/lib/api"
import { fmtTime } from "@/lib/status"

const NAV = [
  { to: "/", label: "即時指揮" },
  { to: "/replay", label: "歷史回放" },
  { to: "/alerts", label: "警示" },
  { to: "/districts", label: "區域分析" },
  { to: "/about", label: "關於" },
]

export function RootLayout() {
  const path = useRouterState({ select: (s) => s.location.pathname })
  const meta = useQuery({
    queryKey: ["meta"],
    queryFn: api.meta,
    refetchInterval: 60_000,
  })

  const lastTs = meta.data?.realtime?.last_ts
  const fetched = meta.data?.realtime?.fetched_at
  const fresh = fetched ? Date.now() - new Date(fetched).getTime() < 25 * 60_000 : false

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-void">
      <header className="flex shrink-0 items-center gap-4 border-b border-line px-4 py-2.5">
        <Link to="/" className="flex items-baseline gap-2">
          <span
            className="num text-[15px] font-bold tracking-tight"
            style={{ color: "var(--bike)" }}
          >
            YouBike
          </span>
          <span className="text-[14px] font-semibold text-ink">調度指揮台</span>
          <span className="hidden text-[11px] text-ink-faint sm:inline">
            新北市 · 交通局命題
          </span>
        </Link>

        <nav className="ml-2 flex gap-0.5 overflow-x-auto">
          {NAV.map((n) => {
            const active = n.to === "/" ? path === "/" : path.startsWith(n.to)
            return (
              <Link
                key={n.to}
                to={n.to}
                className={`rounded px-2.5 py-1 text-[12px] whitespace-nowrap transition-colors ${
                  active
                    ? "bg-panel-2 text-ink"
                    : "text-ink-dim hover:bg-panel hover:text-ink"
                }`}
              >
                {n.label}
              </Link>
            )
          })}
        </nav>

        <div className="ml-auto flex items-center gap-2 text-right">
          <div className="leading-tight">
            <p className="eyebrow">資料時間</p>
            <p className="num text-[12px] text-ink">{fmtTime(lastTs)}</p>
          </div>
          <span
            className="h-2 w-2 rounded-full"
            style={{ background: fresh ? "var(--st-ok)" : "var(--st-offline)" }}
            title={fresh ? "即時資料更新中（每 10 分鐘）" : "顯示最後一次可用的快照"}
          />
        </div>
      </header>

      <main className="min-h-0 flex-1">
        <Outlet />
      </main>
    </div>
  )
}
