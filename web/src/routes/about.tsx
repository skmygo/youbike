import { useQuery } from "@tanstack/react-query"

import { api } from "@/lib/api"
import { fmtTime } from "@/lib/status"

const PAINS = [
  {
    pain: "看不到全局",
    detail: "現行系統要一站一站查，調度員無法一眼看出全市哪裡在壞。",
    answer: "即時指揮台",
    to: "地圖把 1,500 多站的狀態同時攤開，紅色是沒車、藍色是沒位。",
  },
  {
    pain: "只能事後補救",
    detail: "等到站點空了才知道，車派過去往往已經過了尖峰。",
    answer: "預測模型",
    to: "以歷史型態預測未來 30 分至 3 小時的可借車數與空滿機率。",
  },
  {
    pain: "系統不會主動通知",
    detail: "沒有分級警示，也沒有「先救哪一站」的依據。",
    answer: "警示引擎 + 調度建議",
    to: "三級規則自動盯場，並依嚴重度與歷史需求排出處理順序。",
  },
]

export function AboutPage() {
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta })
  const overview = useQuery({ queryKey: ["overview"], queryFn: api.overview })
  const h = overview.data?.history

  return (
    <div className="h-full overflow-auto">
      <div className="mx-auto max-w-[900px] px-6 py-8">
        <p className="eyebrow">關於這個作品</p>
        <h1 className="mt-2 text-[26px] leading-tight font-semibold">
          把「車去哪了」變成「現在該調哪一台」
        </h1>
        <p className="mt-3 max-w-[68ch] text-[13px] leading-relaxed text-ink-dim">
          新北市政府 AI 黑客松・交通局命題作品。資料來源是主辦方提供的六個月
          YouBike2.0 歷史快照，加上新北市資料開放平台的即時 API——
          歷史用來學型態，即時用來盯現場。
        </p>

        <section className="mt-8">
          <p className="eyebrow mb-3">命題的三個痛點，對應三個模組</p>
          <div className="grid gap-3 md:grid-cols-3">
            {PAINS.map((p) => (
              <div key={p.pain} className="rounded border border-line bg-panel p-4">
                <p className="text-[13px] font-semibold text-st-near">{p.pain}</p>
                <p className="mt-1.5 text-[12px] leading-relaxed text-ink-dim">
                  {p.detail}
                </p>
                <p className="mt-3 border-t border-line-soft pt-3 text-[12px] font-semibold text-ink">
                  → {p.answer}
                </p>
                <p className="mt-1 text-[12px] leading-relaxed text-ink-dim">{p.to}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="mt-8">
          <p className="eyebrow mb-3">資料涵蓋</p>
          <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Fact label="歷史快照" value={h?.n_rows?.toLocaleString() ?? "—"} unit="筆" />
            <Fact label="涵蓋站點" value={h?.n_stations?.toLocaleString() ?? "—"} unit="站" />
            <Fact
              label="全期無車時間占比"
              value={h?.empty_rate != null ? (h.empty_rate * 100).toFixed(2) : "—"}
              unit="%"
              accent="#ff5c5c"
            />
            <Fact
              label="全期無位時間占比"
              value={h?.full_rate != null ? (h.full_rate * 100).toFixed(2) : "—"}
              unit="%"
              accent="#4c8dff"
            />
          </dl>
          <p className="num mt-2 text-[11px] text-ink-faint">
            歷史區間 {h?.first_ts?.slice(0, 10) ?? "—"} ~ {h?.last_ts?.slice(0, 10) ?? "—"}
            　·　即時資料最後更新 {fmtTime(meta.data?.realtime?.fetched_at)}
          </p>
        </section>

        <section className="mt-8">
          <p className="eyebrow mb-3">怎麼做的</p>
          <ul className="space-y-2 text-[12px] leading-relaxed text-ink-dim">
            <li>
              <b className="font-semibold text-ink">資料層</b>　六個月 1 GB CSV
              整成 30 分鐘槽的 parquet（18 MB），修正 Big5 匯出的缺字站名、
              合併重複快照、剔除長期未營運站。查詢一律用 DuckDB 直接讀 parquet。
            </li>
            <li>
              <b className="font-semibold text-ink">排程</b>　Dagster 每 10 分鐘抓一次
              即時資料，接續歷史寫進服務層，重算警示。寫入都是先寫暫存檔再原子更名，
              前台不會讀到半成品。
            </li>
            <li>
              <b className="font-semibold text-ink">判讀品質</b>　有車柱卻同時「沒車也沒位」
              的站會被標成離線，不列入空滿統計——這種站是設備問題，不是調度問題。
            </li>
          </ul>
        </section>
      </div>
    </div>
  )
}

function Fact({
  label,
  value,
  unit,
  accent,
}: {
  label: string
  value: string
  unit: string
  accent?: string
}) {
  return (
    <div className="rounded border border-line bg-panel px-4 py-3">
      <dt className="eyebrow">{label}</dt>
      <dd className="num mt-1 text-[22px] leading-none" style={{ color: accent }}>
        {value}
        <span className="ml-1 text-[11px] text-ink-faint">{unit}</span>
      </dd>
    </div>
  )
}
