import { useQuery } from "@tanstack/react-query"
import ReactECharts from "echarts-for-react"

import { api } from "@/lib/api"

const HORIZONS = ["30", "60", "120", "180"]
const AXIS = "#56637a"
const GRID = "#1b2537"

export function ModelPage() {
  const q = useQuery({ queryKey: ["model-report"], queryFn: api.modelReport })
  const r = q.data

  if (q.isLoading) {
    return <p className="p-10 text-center text-xs text-ink-faint">回測報告載入中…</p>
  }
  if (!r?.available) {
    return (
      <div className="p-10">
        <p className="eyebrow">預測模型 · WP3</p>
        <h1 className="mt-1 text-[19px] font-semibold">回測報告尚未產生</h1>
        <p className="mt-2 max-w-[60ch] text-[12px] leading-relaxed text-ink-dim">
          模型訓練完成後會產生 6 月測試集的回測報告（report.json），這頁就會顯示完整指標。
        </p>
      </div>
    )
  }

  const head = r.headline
  const reg = r.regression ?? {}
  const clf = r.classification
  const ev = r.events
  const imp = r.feature_importance?.reg_h60 ?? r.feature_importance?.reg_h30 ?? []

  return (
    <div className="h-full overflow-y-auto">
      <header className="border-b border-line px-5 py-4">
        <p className="eyebrow">預測模型 · WP3</p>
        <h1 className="mt-1 text-[19px] font-semibold">模型好在哪、差在哪，一次講完</h1>
        <p className="mt-1 max-w-[72ch] text-[12px] leading-relaxed text-ink-dim">
          1–4 月訓練、5 月驗證（早停）、<b className="font-normal text-ink">6 月完全沒被模型看過</b>，
          下面所有數字都出自 6 月測試集。對照組有兩個：
          <b className="font-normal text-ink">現況延續</b>（假設水位不變，短時距的強基準）與
          <b className="font-normal text-ink">上週同時段</b>。
          {r.generated_at && (
            <span className="num text-ink-faint"> · 產生於 {r.generated_at.slice(0, 16).replace("T", " ")}</span>
          )}
        </p>
      </header>

      <div className="space-y-6 px-5 py-4">
        {/* Hero 數字 */}
        {head && (
          <section className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Hero
              label="60 分預測平均誤差"
              value={`${head.mae_bikes_60min.toFixed(2)} 台`}
              sub={`現況延續 ${head.mae_bikes_60min_persistence.toFixed(2)} 台`}
              accent="#21d0a5"
            />
            <Hero
              label="比現況延續好"
              value={`${head.improve_vs_persistence_pct_60min.toFixed(1)}%`}
              sub="同一份 6 月測試集"
              accent="#c084fc"
            />
            <Hero
              label="空車事件偵測率"
              value={`${(head.empty_event_coverage * 100).toFixed(1)}%`}
              sub={`6 月共 ${head.n_empty_events_june.toLocaleString()} 起`}
              accent="#ff5c5c"
            />
            <Hero
              label="平均提前預警"
              value={`${head.empty_event_mean_lead_minutes.toFixed(0)} 分`}
              sub="規則型只能在事發後才報"
              accent="#ffb020"
            />
          </section>
        )}

        {/* 水位預測：四個時距對照 */}
        <section>
          <h2 className="eyebrow mb-2">水位預測 · 平均絕對誤差（台車，越低越好）</h2>
          <div className="rounded border border-line bg-panel p-3">
            <ReactECharts
              style={{ height: 240 }}
              opts={{ renderer: "svg" }}
              option={{
                backgroundColor: "transparent",
                grid: { left: 40, right: 12, top: 28, bottom: 26 },
                legend: {
                  top: 0,
                  textStyle: { color: AXIS, fontSize: 11 },
                  itemWidth: 10,
                  itemHeight: 8,
                },
                tooltip: {
                  trigger: "axis",
                  backgroundColor: "#121a2a",
                  borderColor: "#253148",
                  textStyle: { color: "#e6edf8", fontSize: 11 },
                  valueFormatter: (v: number) => `${v.toFixed(3)} 台`,
                },
                xAxis: {
                  type: "category",
                  data: HORIZONS.map((h) => `${h} 分後`),
                  axisLine: { lineStyle: { color: "#253148" } },
                  axisLabel: { color: AXIS, fontSize: 11 },
                },
                yAxis: {
                  type: "value",
                  axisLabel: { color: AXIS, fontSize: 10 },
                  splitLine: { lineStyle: { color: GRID } },
                },
                series: [
                  {
                    name: "LightGBM",
                    type: "bar",
                    itemStyle: { color: "#21d0a5" },
                    data: HORIZONS.map((h) => reg[h]?.lgbm?.mae_bikes ?? null),
                  },
                  {
                    name: "現況延續",
                    type: "bar",
                    itemStyle: { color: "#4c8dff" },
                    data: HORIZONS.map((h) => reg[h]?.persistence?.mae_bikes ?? null),
                  },
                  {
                    name: "上週同時段",
                    type: "bar",
                    itemStyle: { color: "#56637a" },
                    data: HORIZONS.map((h) => reg[h]?.lastweek?.mae_bikes ?? null),
                  },
                ],
              }}
            />
            <table className="mt-2 w-full text-[12px]">
              <thead>
                <tr className="border-b border-line-soft text-left">
                  <Th>時距</Th>
                  <Th right>LightGBM</Th>
                  <Th right>現況延續</Th>
                  <Th right>上週同時段</Th>
                  <Th right>贏現況延續</Th>
                </tr>
              </thead>
              <tbody>
                {HORIZONS.map((h) => {
                  const p = reg[h]
                  if (!p) return null
                  const gain = p.lgbm.improve_vs_persistence_pct ?? 0
                  return (
                    <tr key={h} className="border-b border-line-soft">
                      <td className="px-3 py-1.5 text-ink-dim">{h} 分後</td>
                      <td className="num px-3 py-1.5 text-right text-ink">{p.lgbm.mae_bikes.toFixed(3)}</td>
                      <td className="num px-3 py-1.5 text-right text-ink-dim">
                        {p.persistence.mae_bikes.toFixed(3)}
                      </td>
                      <td className="num px-3 py-1.5 text-right text-ink-faint">
                        {p.lastweek.mae_bikes.toFixed(3)}
                      </td>
                      <td
                        className="num px-3 py-1.5 text-right"
                        style={{ color: gain > 0 ? "#21d0a5" : "#ff5c5c" }}
                      >
                        {gain > 0 ? "+" : ""}
                        {gain.toFixed(1)}%
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            <p className="mt-2 text-[11px] leading-relaxed text-ink-faint">
              短時距（30 分）現況延續本來就很強，模型只小勝；時距拉長，模型的優勢才會展開——
              這正是調度真正需要的區間（派車出去也要時間）。
            </p>
          </div>
        </section>

        {/* 事件級預警 */}
        {ev && (
          <section>
            <h2 className="eyebrow mb-2">事件級預警 · 真的能提前多久告訴你</h2>
            <div className="grid gap-3 md:grid-cols-2">
              {(["empty", "full"] as const).map((k) => {
                const op = ev[k]?.at_operational_threshold
                const strict = ev[k]?.at_alert_threshold
                if (!op || !op.n_events) return null
                return (
                  <div key={k} className="rounded border border-line bg-panel p-3">
                    <p className="text-[13px] text-ink">
                      {k === "empty" ? "無車可借事件" : "無位可還事件"}
                      <span className="num ml-2 text-[11px] text-ink-faint">
                        6 月 {op.n_events.toLocaleString()} 起
                      </span>
                    </p>
                    <dl className="mt-2 space-y-1.5 text-[12px]">
                      <Row label="事件偵測率" value={pct(op.coverage)} color="#21d0a5" />
                      <Row
                        label="平均提前"
                        value={op.mean_lead_minutes != null ? `${op.mean_lead_minutes.toFixed(0)} 分` : "—"}
                        color="#ffb020"
                      />
                      <Row label="誤報率" value={pct(op.false_alarm_rate)} />
                      <Row
                        label="每站每天警報數"
                        value={op.alerts_per_station_per_day?.toFixed(2) ?? "—"}
                      />
                      <Row label="規則型可提前" value="0 分（事發後才知道）" color="#ff5c5c" />
                    </dl>
                    {op.lead_distribution && (
                      <p className="num mt-2 text-[11px] text-ink-faint">
                        提前分佈：
                        {Object.entries(op.lead_distribution)
                          .map(([h, n]) => `${h}分 ${n}`)
                          .join(" · ")}
                      </p>
                    )}
                    {strict?.coverage != null && (
                      <p className="mt-2 border-t border-line-soft pt-2 text-[11px] leading-relaxed text-ink-faint">
                        同一組事件，若把門檻拉到規劃書的 70%：偵測率降到{" "}
                        <span className="num">{pct(strict.coverage)}</span>、誤報率{" "}
                        <span className="num">{pct(strict.false_alarm_rate)}</span>——
                        少擾民，但大部分事件會漏掉。
                      </p>
                    )}
                  </div>
                )
              })}
            </div>
            <p className="mt-2 text-[11px] leading-relaxed text-ink-faint">
              上面的數字採<b className="font-normal text-ink-dim">營運門檻</b>（驗證集上 F1 最佳），
              也就是線上警示與調度單實際在用的設定。
            </p>
          </section>
        )}

        {/* 分類指標 */}
        {clf && (
          <section>
            <h2 className="eyebrow mb-2">空／滿事件分類 · 逐時距指標</h2>
            <div className="overflow-x-auto rounded border border-line bg-panel">
              <table className="w-full text-[12px]">
                <thead>
                  <tr className="border-b border-line text-left">
                    <Th>事件</Th>
                    <Th>時距</Th>
                    <Th right>發生率</Th>
                    <Th right>PR-AUC</Th>
                    <Th right>ROC-AUC</Th>
                    <Th right>F1@70%</Th>
                    <Th right>精確率@70%</Th>
                    <Th right>召回率@70%</Th>
                    <Th right>規則型 F1</Th>
                  </tr>
                </thead>
                <tbody>
                  {(["empty", "full"] as const).flatMap((k) =>
                    HORIZONS.map((h) => {
                      const m = clf[k]?.[h]
                      if (!m) return null
                      return (
                        <tr key={`${k}-${h}`} className="border-b border-line-soft">
                          <td className="px-3 py-1.5 text-ink-dim">
                            {k === "empty" ? "無車" : "滿位"}
                          </td>
                          <td className="num px-3 py-1.5 text-ink-dim">{h} 分</td>
                          <td className="num px-3 py-1.5 text-right text-ink-faint">{pct(m.pos_rate)}</td>
                          <td className="num px-3 py-1.5 text-right text-ink">{m.pr_auc.toFixed(3)}</td>
                          <td className="num px-3 py-1.5 text-right text-ink-dim">{m.roc_auc.toFixed(3)}</td>
                          <td className="num px-3 py-1.5 text-right text-ink">
                            {m.at_alert_threshold.f1.toFixed(3)}
                          </td>
                          <td className="num px-3 py-1.5 text-right text-ink-dim">
                            {m.at_alert_threshold.precision.toFixed(3)}
                          </td>
                          <td className="num px-3 py-1.5 text-right text-ink-dim">
                            {m.at_alert_threshold.recall.toFixed(3)}
                          </td>
                          <td className="num px-3 py-1.5 text-right text-ink-faint">
                            {m.persistence_rule.f1.toFixed(3)}
                          </td>
                        </tr>
                      )
                    }),
                  )}
                </tbody>
              </table>
            </div>
            <p className="mt-2 text-[11px] leading-relaxed text-ink-faint">
              預警門檻固定在 70%（規劃書定義），是刻意偏保守的設定：精確率高、少擾民，代價是召回率沒有最佳化 F1 時高。
              報告同時附上驗證集最佳門檻下的表現，讓調度單位自己決定要多敏感。
            </p>
          </section>
        )}

        {/* 特徵重要度 */}
        {imp.length > 0 && (
          <section>
            <h2 className="eyebrow mb-2">模型在看什麼 · 60 分模型的特徵重要度（gain）</h2>
            <div className="rounded border border-line bg-panel p-3">
              <ReactECharts
                style={{ height: Math.max(220, imp.length * 18) }}
                opts={{ renderer: "svg" }}
                option={{
                  backgroundColor: "transparent",
                  grid: { left: 130, right: 20, top: 8, bottom: 24 },
                  tooltip: {
                    trigger: "axis",
                    axisPointer: { type: "shadow" },
                    backgroundColor: "#121a2a",
                    borderColor: "#253148",
                    textStyle: { color: "#e6edf8", fontSize: 11 },
                  },
                  xAxis: {
                    type: "value",
                    axisLabel: { color: AXIS, fontSize: 10, formatter: (v: number) => shortNum(v) },
                    splitLine: { lineStyle: { color: GRID } },
                  },
                  yAxis: {
                    type: "category",
                    data: [...imp].reverse().map((f) => f.feature),
                    axisLine: { lineStyle: { color: "#253148" } },
                    axisLabel: { color: AXIS, fontSize: 10 },
                  },
                  series: [
                    {
                      type: "bar",
                      itemStyle: { color: "#4c8dff" },
                      data: [...imp].reverse().map((f) => f.gain),
                    },
                  ],
                }}
              />
            </div>
          </section>
        )}

        {/* 方法 */}
        <section>
          <h2 className="eyebrow mb-2">做法與誠實揭露</h2>
          <div className="grid gap-3 text-[12px] leading-relaxed md:grid-cols-2">
            <div className="rounded border border-line bg-panel p-3 text-ink-dim">
              <p className="mb-1 text-ink">怎麼切、怎麼防洩漏</p>
              <ul className="list-disc space-y-1 pl-4">
                <li>時間序切分不洗牌：1–4 月訓練、5 月驗證、6 月測試</li>
                <li>歷史常態（norm_*）只用訓練期統計，不讓 5、6 月的資訊回流</li>
                <li>目標欄一律用 LEAD 取未來值，特徵只用當下與過去</li>
                {r.data?.n_features && <li>共 {r.data.n_features} 個特徵，含 lag／rolling／鄰域／分群／歷史常態</li>}
              </ul>
            </div>
            <div className="rounded border border-line bg-panel p-3 text-ink-dim">
              <p className="mb-1 text-ink">限制</p>
              <ul className="list-disc space-y-1 pl-4">
                <li>訓練資料抽樣（本機同時是正式服務主機，記憶體要留給線上服務）</li>
                <li>沒有天氣、活動、學期等外生變數，雨天與大型活動會失準</li>
                <li>假日是資料驅動偵測出來的，不是官方行事曆</li>
                <li>線上推論的近期 lag 用「同站同時段的上一次觀測」暖機，即時資料累積後會自動變準</li>
              </ul>
            </div>
          </div>
        </section>
      </div>
    </div>
  )
}

function pct(v: number | null | undefined): string {
  return v == null ? "—" : `${(v * 100).toFixed(1)}%`
}

function shortNum(v: number): string {
  if (v >= 1e6) return `${(v / 1e6).toFixed(1)}M`
  if (v >= 1e3) return `${(v / 1e3).toFixed(0)}k`
  return String(Math.round(v))
}

function Hero({
  label,
  value,
  sub,
  accent,
}: {
  label: string
  value: string
  sub: string
  accent: string
}) {
  return (
    <div className="rounded border border-line bg-panel px-3 py-2.5">
      <p className="eyebrow">{label}</p>
      <p className="num mt-1 text-[24px] leading-none" style={{ color: accent }}>
        {value}
      </p>
      <p className="mt-1.5 text-[11px] text-ink-faint">{sub}</p>
    </div>
  )
}

function Th({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return (
    <th className={`eyebrow px-3 py-2 font-normal ${right ? "text-right" : "text-left"}`}>
      {children}
    </th>
  )
}

function Row({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-line-soft pb-1.5">
      <dt className="text-ink-dim">{label}</dt>
      <dd className="num" style={{ color: color ?? "var(--ink)" }}>
        {value}
      </dd>
    </div>
  )
}
