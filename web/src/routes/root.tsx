import { Link, Outlet } from "@tanstack/react-router"

export function RootLayout() {
  return (
    <div className="min-h-svh bg-background text-foreground">
      <nav className="flex items-center gap-4 border-b border-border px-6 py-3 text-sm">
        <Link
          to="/"
          className="text-muted-foreground hover:text-foreground [&.active]:text-foreground [&.active]:font-medium"
        >
          首頁
        </Link>
        <Link
          to="/about"
          className="text-muted-foreground hover:text-foreground [&.active]:text-foreground [&.active]:font-medium"
        >
          關於
        </Link>
      </nav>
      <Outlet />
    </div>
  )
}
