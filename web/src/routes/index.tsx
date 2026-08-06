import { useQuery } from "@tanstack/react-query"

async function fetchHealth(): Promise<unknown> {
  const res = await fetch("/api/health")
  if (!res.ok) {
    throw new Error(`API 回應錯誤：${res.status}`)
  }
  return res.json()
}

export function IndexPage() {
  const { data, isError } = useQuery({
    queryKey: ["health"],
    queryFn: fetchHealth,
    retry: 1,
  })

  return (
    <main className="flex min-h-[calc(100svh-49px)] flex-col items-center justify-center gap-4 px-6 text-center">
      <h1 className="text-4xl font-bold tracking-tight sm:text-5xl">
        YouBike 智慧調度平台
      </h1>
      <p className="text-lg text-muted-foreground">
        新北市政府 AI 黑客松・交通局命題
      </p>
      <p className="mt-8 font-mono text-xs text-muted-foreground/70">
        {isError
          ? "API 連線中…"
          : data !== undefined
            ? JSON.stringify(data)
            : "API 連線中…"}
      </p>
    </main>
  )
}
