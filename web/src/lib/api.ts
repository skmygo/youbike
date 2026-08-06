/** 後端 API client。所有型別對應 api/routes.py 的回傳。 */

export type StationStatus =
  | "normal"
  | "near_empty"
  | "near_full"
  | "empty"
  | "full"
  | "offline"
  | "unknown"

export interface Station {
  station_id: number
  name: string
  district: string | null
  lon: number
  lat: number
  capacity_docks: number | null
  always_empty: boolean | null
  ts: string | null
  bikes: number | null
  docks_avail: number | null
  docks_total: number | null
  occ_rate: number | null
  status: StationStatus
}

export interface StationsResponse {
  as_of: string | null
  count: number
  stations: Station[]
}

export type AlertLevel = "critical" | "warning" | "notice"
export type AlertKind = "empty" | "full" | "near_empty" | "near_full"

export interface Alert {
  station_id: number
  name: string
  district: string | null
  lon: number
  lat: number
  capacity_docks: number | null
  ts: string
  bikes: number
  docks_avail: number
  docks_total: number
  kind: AlertKind
  duration_min: number
  duration_capped: boolean
  level: AlertLevel
}

export interface AlertsResponse {
  source: "pipeline" | "live"
  count: number
  alerts: Alert[]
}

export interface Overview {
  now?: {
    as_of: string
    n_stations: number
    bikes: number
    docks_total: number
    occ_rate: number
    n_empty: number
    n_full: number
    n_offline: number
    n_risk: number
  }
  history?: {
    first_ts: string
    last_ts: string
    n_rows: number
    n_stations: number
    empty_rate: number
    full_rate: number
  }
}

export interface DistrictRow {
  district: string
  n_stations: number
  docks_total: number
  bikes: number
  docks_avail: number
  occ_rate: number
  n_empty: number
  n_full: number
  n_offline: number
  n_near_empty: number
  n_near_full: number
}

export interface PulsePoint {
  ts: string
  slot: number
  n_stations: number
  n_empty: number
  n_full: number
  n_risk: number
  bikes: number
  occ_rate: number
}

export interface HistoryPoint {
  ts: string
  bikes: number
  docks_avail: number
  docks_total: number
  occ_rate: number | null
}

export interface StationDetail {
  station_id: number
  name: string
  district: string | null
  lon: number
  lat: number
  capacity_docks: number | null
  first_ts: string
  last_ts: string
  n_snapshots: number
  always_empty: boolean
  current?: {
    ts: string
    bikes: number
    docks_avail: number
    docks_total: number
    status: StationStatus
  } | null
  stats?: {
    n_snapshots: number
    bikes_mean: number
    empty_rate: number
    full_rate: number
    occ_rate: number
  } | null
}

export interface HourlyRow {
  isodow: number
  slot: number
  n: number
  empty_rate: number
  full_rate: number
  occ_rate: number
  bikes_p10?: number
  bikes_p50?: number
  bikes_p90?: number
  bikes_mean?: number
}

export interface Meta {
  data: Record<string, unknown>
  realtime?: { last_ts: string; fetched_at: string; n_stations: number }
  history?: { first_ts: string; last_ts: string; n_rows: number; n_stations: number }
}

export interface ReplayDay {
  day: string
  n_rows: number
  n_slots: number
}

// ── 預測 / 調度（M5）──────────────────────────────────────────────────────
export interface ForecastRow {
  station_id: number
  name: string
  district: string
  base_ts: string
  horizon: number
  now_bikes: number
  now_docks_avail: number
  docks_total: number
  pred_ratio: number
  pred_bikes: number
  pred_docks: number
  proba_empty: number
  proba_full: number
  alert_empty: boolean
  alert_full: boolean
  is_live: boolean
  risk?: number
}

export interface ForecastMeta {
  base_ts?: string
  generated_at?: string
  n_stations?: number
  n_live_stations?: number
  live_slot_ratio?: number
  bridged_slot_ratio?: number
  alert_threshold?: number
  alerts_60min?: { empty: number; full: number }
  note?: string
}

export interface ForecastAlert {
  station_id: number
  name: string
  district: string
  base_ts: string
  horizon: number
  now_bikes: number
  now_docks_avail: number
  docks_total: number
  pred_bikes: number
  pred_docks: number
  proba_empty: number
  proba_full: number
  kind: "empty" | "full"
  proba: number
}

export interface DispatchTask {
  to_station: number
  to_name: string
  district: string
  now_bikes: number
  to_pred_bikes: number
  to_capacity: number
  proba_empty: number
  need_bikes: number
  from_station: number | null
  from_name: string | null
  spare_bikes: number | null
  proba_full: number | null
  distance_km: number | null
  move_bikes: number
  // 降級（規則型）模式下改回這幾欄
  level?: string
  duration_min?: number
}

export interface BacktestHeadline {
  mae_bikes_60min: number
  mae_bikes_60min_persistence: number
  improve_vs_persistence_pct_60min: number
  empty_event_coverage: number
  empty_event_mean_lead_minutes: number
  empty_f1_60min: number
  full_event_coverage: number
  full_event_mean_lead_minutes: number
  n_empty_events_june: number
  n_full_events_june: number
}

export interface ModelReport {
  available: boolean
  generated_at?: string
  data?: Record<string, unknown>
  model?: Record<string, unknown>
  regression?: Record<string, Record<string, { mae_bikes: number; mae_ratio: number; improve_vs_persistence_pct?: number }>>
  classification?: Record<string, Record<string, Record<string, unknown>>>
  events?: Record<string, Record<string, number>>
  valid_baselines?: Record<string, unknown>
  feature_importance?: Record<string, Array<{ feature: string; gain: number }>>
  headline?: BacktestHeadline
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`/api${path}`)
  if (!res.ok) throw new Error(`${res.status} ${path}`)
  return res.json() as Promise<T>
}

export const api = {
  meta: () => get<Meta>("/meta"),
  stations: () => get<StationsResponse>("/stations"),
  station: (id: number) => get<StationDetail>(`/stations/${id}`),
  stationHistory: (id: number, days = 7) =>
    get<{ points: HistoryPoint[] }>(`/stations/${id}/history?days=${days}`),
  alerts: () => get<AlertsResponse>("/alerts"),
  overview: () => get<Overview>("/stats/overview"),
  districts: () => get<{ districts: DistrictRow[] }>("/stats/districts"),
  pulse: (date?: string) =>
    get<{
      date: string
      isodow?: number
      points: PulsePoint[]
      baseline?: Array<{ slot: number; n_empty: number; n_full: number }>
    }>(
      `/stats/pulse${date ? `?date=${date}` : ""}`,
    ),
  hourly: (stationId?: number) =>
    get<{ rows: HourlyRow[] }>(
      `/stats/hourly${stationId != null ? `?station_id=${stationId}` : ""}`,
    ),
  worst: (metric: "empty" | "full" = "empty", limit = 20) =>
    get<{ rows: Array<{ station_id: number; name: string; district: string; empty_rate: number; full_rate: number; n: number; capacity_docks: number }> }>(
      `/stats/worst?metric=${metric}&limit=${limit}`,
    ),
  replay: (ts: string) => get<StationsResponse & { ts: string }>(`/replay?ts=${encodeURIComponent(ts)}`),
  replayDays: () => get<{ days: ReplayDay[] }>("/replay/days"),

  forecast: (horizon = 60, opts: { district?: string; riskOnly?: boolean; limit?: number } = {}) => {
    const q = new URLSearchParams({ horizon: String(horizon) })
    if (opts.district) q.set("district", opts.district)
    if (opts.riskOnly) q.set("risk_only", "true")
    if (opts.limit) q.set("limit", String(opts.limit))
    return get<{ count: number; horizon: number; meta: ForecastMeta; forecast: ForecastRow[]; status?: string }>(
      `/forecast?${q}`,
    )
  },
  forecastMeta: () =>
    get<{ available: boolean; meta: ForecastMeta; backtest_headline: Partial<BacktestHeadline> }>(
      "/forecast/meta",
    ),
  forecastStation: (id: number) =>
    get<{ station_id: number; meta: ForecastMeta; forecast: ForecastRow[] }>(`/forecast/station/${id}`),
  forecastAlerts: (horizon = 60, district?: string) =>
    get<{ count: number; horizon: number; meta: ForecastMeta; alerts: ForecastAlert[] }>(
      `/forecast/alerts?horizon=${horizon}${district ? `&district=${encodeURIComponent(district)}` : ""}`,
    ),
  dispatch: (horizon = 60, limit = 50) =>
    get<{
      count: number
      mode: "forecast" | "rule" | "unavailable"
      horizon: number | null
      total_move_bikes?: number
      meta: ForecastMeta
      tasks: DispatchTask[]
    }>(`/dispatch?horizon=${horizon}&limit=${limit}`),
  modelReport: () => get<ModelReport>("/model/report"),
}
