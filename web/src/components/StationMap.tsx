import { useEffect, useMemo, useRef } from "react"
import {
  Map as MapLibreMap,
  NavigationControl,
  Popup,
  type DataDrivenPropertyValueSpecification,
  type GeoJSONSource,
  type MapLayerMouseEvent,
} from "maplibre-gl"
import "maplibre-gl/dist/maplibre-gl.css"

import type { Station } from "@/lib/api"
import { STATUS } from "@/lib/status"

/** 新北市範圍，開場視角 */
const CENTER: [number, number] = [121.51, 25.0]
const ZOOM = 10.6

const CARTO_TILES = [
  "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png",
  "https://b.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png",
  "https://c.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png",
]

/** 狀態 → 顏色。MapLibre 的 expression 型別要求固定長度的 tuple，
    這裡是從 STATUS 動態展開的，所以明確標成 paint 屬性型別。 */
const COLOR_BY_STATUS = [
  "match",
  ["get", "status"],
  ...Object.entries(STATUS).flatMap(([k, v]) => [k, v.color]),
  "#48546b",
] as unknown as DataDrivenPropertyValueSpecification<string>

interface Props {
  stations: Station[]
  selectedId?: number | null
  onSelect?: (id: number) => void
  /** 正常時只把有問題的站畫大；設 false 則所有站同尺寸 */
  emphasizeProblems?: boolean
}

export function StationMap({
  stations,
  selectedId,
  onSelect,
  emphasizeProblems = true,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<MapLibreMap | null>(null)
  const readyRef = useRef(false)
  const onSelectRef = useRef(onSelect)
  onSelectRef.current = onSelect

  const geojson = useMemo(
    () => ({
      type: "FeatureCollection" as const,
      features: stations
        .filter((s) => s.lon && s.lat)
        .map((s) => ({
          type: "Feature" as const,
          id: s.station_id,
          geometry: { type: "Point" as const, coordinates: [s.lon, s.lat] },
          properties: {
            station_id: s.station_id,
            name: s.name,
            district: s.district ?? "",
            status: s.status,
            bikes: s.bikes ?? 0,
            docks_avail: s.docks_avail ?? 0,
            docks_total: s.docks_total ?? 0,
            problem:
              s.status === "empty" ||
              s.status === "full" ||
              s.status === "near_empty" ||
              s.status === "near_full"
                ? 1
                : 0,
          },
        })),
    }),
    [stations],
  )

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return

    const map = new MapLibreMap({
      container: containerRef.current,
      center: CENTER,
      zoom: ZOOM,
      attributionControl: { compact: true },
      style: {
        version: 8,
        sources: {
          carto: {
            type: "raster",
            tiles: CARTO_TILES,
            tileSize: 256,
            attribution:
              '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> · © <a href="https://carto.com/attributions">CARTO</a>',
          },
        },
        layers: [{ id: "carto", type: "raster", source: "carto" }],
      },
    })
    mapRef.current = map
    map.addControl(new NavigationControl({ showCompass: false }), "top-right")

    const popup = new Popup({
      closeButton: false,
      closeOnClick: false,
      offset: 10,
      maxWidth: "260px",
    })

    map.on("load", () => {
      map.addSource("stations", { type: "geojson", data: geojson })

      // 有問題的站加一圈光暈，讓紅／琥珀在縮小視角下也看得見
      map.addLayer({
        id: "station-glow",
        type: "circle",
        source: "stations",
        filter: ["==", ["get", "problem"], 1],
        paint: {
          "circle-radius": [
            "interpolate", ["linear"], ["zoom"],
            9, 6, 12, 12, 15, 22,
          ],
          "circle-color": COLOR_BY_STATUS,
          "circle-opacity": 0.16,
          "circle-blur": 0.6,
        },
      })

      map.addLayer({
        id: "station-dot",
        type: "circle",
        source: "stations",
        paint: {
          "circle-radius": emphasizeProblems
            ? [
                "interpolate", ["linear"], ["zoom"],
                9, ["case", ["==", ["get", "problem"], 1], 3.6, 2.2],
                12, ["case", ["==", ["get", "problem"], 1], 6, 4],
                15, ["case", ["==", ["get", "problem"], 1], 11, 8],
              ]
            : ["interpolate", ["linear"], ["zoom"], 9, 2.6, 12, 5, 15, 9],
          "circle-color": COLOR_BY_STATUS,
          "circle-opacity": [
            "case", ["==", ["get", "status"], "offline"], 0.45, 0.9,
          ],
          "circle-stroke-width": [
            "case", ["boolean", ["feature-state", "selected"], false], 2, 0.5,
          ],
          "circle-stroke-color": [
            "case",
            ["boolean", ["feature-state", "selected"], false],
            "#ffd400",
            "rgba(10,15,26,0.85)",
          ],
        },
      })
      readyRef.current = true

      map.on("mouseenter", "station-dot", () => {
        map.getCanvas().style.cursor = "pointer"
      })
      map.on("mouseleave", "station-dot", () => {
        map.getCanvas().style.cursor = ""
        popup.remove()
      })
      map.on("mousemove", "station-dot", (e: MapLayerMouseEvent) => {
        const f = e.features?.[0]
        if (!f) return
        const p = f.properties as Record<string, string | number>
        const st = STATUS[p.status as keyof typeof STATUS] ?? STATUS.unknown
        popup
          .setLngLat((f.geometry as { coordinates: [number, number] }).coordinates)
          .setHTML(
            `<div style="padding:8px 10px;font-size:12px;line-height:1.5">
               <div style="font-weight:600;margin-bottom:2px">${p.name}</div>
               <div style="color:#8493ac;font-size:11px;margin-bottom:6px">${p.district}</div>
               <div style="display:flex;gap:10px;align-items:center">
                 <span style="color:${st.color}">● ${st.label}</span>
                 <span style="font-family:ui-monospace,monospace;color:#e6edf8">
                   可借 ${p.bikes} · 可還 ${p.docks_avail}
                 </span>
               </div>
             </div>`,
          )
          .addTo(map)
      })
      map.on("click", "station-dot", (e: MapLayerMouseEvent) => {
        const f = e.features?.[0]
        if (f?.properties?.station_id != null) {
          onSelectRef.current?.(Number(f.properties.station_id))
        }
      })
    })

    return () => {
      popup.remove()
      map.remove()
      mapRef.current = null
      readyRef.current = false
    }
    // 只建立一次；資料更新走下面的 setData
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !readyRef.current) return
    const src = map.getSource("stations") as GeoJSONSource | undefined
    src?.setData(geojson)
  }, [geojson])

  const prevSelected = useRef<number | null>(null)
  useEffect(() => {
    const map = mapRef.current
    if (!map || !readyRef.current) return
    if (prevSelected.current != null) {
      map.setFeatureState(
        { source: "stations", id: prevSelected.current },
        { selected: false },
      )
    }
    if (selectedId != null) {
      map.setFeatureState({ source: "stations", id: selectedId }, { selected: true })
    }
    prevSelected.current = selectedId ?? null
  }, [selectedId])

  return <div ref={containerRef} className="h-full w-full" />
}
