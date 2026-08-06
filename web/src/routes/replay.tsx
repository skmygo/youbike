import { useEffect, useMemo, useRef, useState } from "react"
import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { Pause, Play } from "lucide-react"

import { PulseRibbon } from "@/components/PulseRibbon"
import { StationDrawer } from "@/components/StationDrawer"
import { StationMap } from "@/components/StationMap"
import { api } from "@/lib/api"
import { STATUS, WEEKDAY, slotLabel } from "@/lib/status"

const STEP_MS = 700

export function ReplayPage() {
  const [date, setDate] = useState<string | null>(null)
  const [slot, setSlot] = useState(16) // 08:00，通勤尖峰
  const [playing, setPlaying] = useState(false)
  const [selected, setSelected] = useState<number | null>(null)

  const days = useQuery({ queryKey: ["replay-days"], queryFn: api.replayDays })

  // 預設挑一個資料完整的日子：倒數第二天（最後一天可能只有半天）
  useEffect(() => {
    if (date || !days.data?.days?.length) return
    const list = days.data.days.filter((d) => d.n_slots >= 40)
    setDate((list[list.length - 1] ?? days.data.days[days.data.days.length - 1]).day)
  }, [days.data, date])

  const ts = useMemo(() => {
    if (!date) return null
    const h = String(Math.floor(slot / 2)).padStart(2, "0")
    const m = slot % 2 === 0 ? "00" : "30"
    return `${date}T${h}:${m}:00`
  }, [date, slot])

  const replay = useQuery({
    queryKey: ["replay", ts],
    queryFn: () => api.replay(ts as string),
    enabled: ts != null,
    placeholderData: keepPreviousData,
  })
  const pulse = useQuery({
    queryKey: ["pulse", date],
    queryFn: () => api.pulse(date as string),
    enabled: date != null,
  })

  const timer = useRef<number | null>(null)
  useEffect(() => {
    if (!playing) return
    timer.current = window.setInterval(
      () => setSlot((s) => (s + 1) % 48),
      STEP_MS,
    )
    return () => {
      if (timer.current) window.clearInterval(timer.current)
    }
  }, [playing])

  const stations = replay.data?.stations ?? []
  const counts = useMemo(() => {
    const c: Record<string, number> = {}
    for (const s of stations) c[s.status] = (c[s.status] ?? 0) + 1
    return c
  }, [stations])

  const weekday = date ? WEEKDAY[(new Date(date).getDay() + 6) % 7] : ""

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-3 border-b border-line px-4 py-2.5">
        <div>
          <p className="eyebrow">回放日期</p>
          <select
            value={date ?? ""}
            onChange={(e) => setDate(e.target.value)}
            className="num mt-0.5 rounded border border-line bg-panel px-2 py-1 text-[12px] text-ink"
          >
            {days.data?.days?.map((d) => (
              <option key={d.day} value={d.day}>
                {d.day}（{d.n_slots} 個時段）
              </option>
            ))}
          </select>
        </div>

        <button
          type="button"
          onClick={() => setPlaying((p) => !p)}
          className="flex items-center gap-1.5 rounded border border-line bg-panel px-3 py-1.5 text-[12px] text-ink transition-colors hover:bg-panel-2"
        >
          {playing ? <Pause size={13} /> : <Play size={13} />}
          {playing ? "暫停" : "播放一天"}
        </button>

        <div className="flex min-w-[220px] flex-1 items-center gap-3">
          <span className="num w-[86px] shrink-0 text-[20px] leading-none text-ink">
            {slotLabel(slot)}
          </span>
          <input
            type="range"
            className="timeline flex-1"
            min={0}
            max={47}
            step={1}
            value={slot}
            onChange={(e) => setSlot(Number(e.target.value))}
            aria-label="回放時間"
          />
        </div>

        <div className="flex items-center gap-3">
          {(["empty", "full", "near_empty"] as const).map((k) => (
            <span key={k} className="flex items-center gap-1.5 text-[11px] text-ink-dim">
              <span
                className="h-2 w-2 rounded-full"
                style={{ background: STATUS[k].color }}
              />
              {k === "near_empty" ? "將空滿" : STATUS[k].label}
              <b className="num font-normal text-ink">
                {k === "near_empty"
                  ? (counts.near_empty ?? 0) + (counts.near_full ?? 0)
                  : (counts[k] ?? 0)}
              </b>
            </span>
          ))}
          <span className="num text-[11px] text-ink-faint">
            {date} 星期{weekday}
          </span>
        </div>
      </div>

      <div className="relative min-h-0 flex-1">
        <StationMap
          stations={stations}
          selectedId={selected}
          onSelect={setSelected}
        />
        <StationDrawer stationId={selected} onClose={() => setSelected(null)} />
      </div>

      <div className="shrink-0 border-t border-line px-4 py-2">
        <PulseRibbon
          points={pulse.data?.points ?? []}
          currentSlot={slot}
          onSlotSelect={(s) => {
            setPlaying(false)
            setSlot(s)
          }}
          label={`${date ?? ""} 全市空滿脈搏 · 點選時段跳轉`}
        />
      </div>
    </div>
  )
}
