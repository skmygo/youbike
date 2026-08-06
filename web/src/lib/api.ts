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
    get<{ date: string; points: PulsePoint[] }>(
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
}
