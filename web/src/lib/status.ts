import type { AlertLevel, StationStatus } from "@/lib/api"

/** 站點狀態的單一事實來源：地圖燈號、警示分級、圖例、圖表都從這裡取色。 */
export const STATUS: Record<
  StationStatus,
  { label: string; color: string; order: number }
> = {
  empty: { label: "已空", color: "#ff5c5c", order: 0 },
  full: { label: "已滿", color: "#4c8dff", order: 1 },
  near_empty: { label: "將空", color: "#ffb020", order: 2 },
  near_full: { label: "將滿", color: "#ffb020", order: 3 },
  normal: { label: "正常", color: "#21d0a5", order: 4 },
  offline: { label: "離線", color: "#48546b", order: 5 },
  unknown: { label: "無資料", color: "#48546b", order: 6 },
}

export const LEVEL: Record<
  AlertLevel,
  { label: string; color: string; desc: string }
> = {
  critical: { label: "嚴重", color: "#ff5c5c", desc: "已空或已滿持續 60 分鐘以上" },
  warning: { label: "警戒", color: "#ffb020", desc: "已空或已滿" },
  notice: { label: "注意", color: "#8493ac", desc: "可借或可還剩 2 台以內" },
}

export const KIND_LABEL: Record<string, string> = {
  empty: "無車可借",
  full: "無位可還",
  near_empty: "快沒車",
  near_full: "快滿位",
}

/** 2026-08-06T23:30:00 → 08/06 23:30 */
export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "—"
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return "—"
  const p = (n: number) => String(n).padStart(2, "0")
  return `${p(d.getMonth() + 1)}/${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

export function fmtClock(iso: string | null | undefined): string {
  if (!iso) return "—"
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return "—"
  const p = (n: number) => String(n).padStart(2, "0")
  return `${p(d.getHours())}:${p(d.getMinutes())}`
}

/** 持續分鐘 → 人看的長度；capped 代表觀察窗看不到起點 */
export function fmtDuration(min: number, capped = false): string {
  if (min <= 0) return capped ? "剛偵測到" : "—"
  const h = Math.floor(min / 60)
  const m = min % 60
  const base = h > 0 ? (m > 0 ? `${h} 小時 ${m} 分` : `${h} 小時`) : `${m} 分`
  return capped ? `≥ ${base}` : base
}

export const WEEKDAY = ["一", "二", "三", "四", "五", "六", "日"]

/** 0..47 半小時槽 → "08:30" */
export function slotLabel(slot: number): string {
  const h = Math.floor(slot / 2)
  const m = slot % 2 === 0 ? "00" : "30"
  return `${String(h).padStart(2, "0")}:${m}`
}
