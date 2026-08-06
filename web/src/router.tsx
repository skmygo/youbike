import { createRootRoute, createRoute, createRouter } from "@tanstack/react-router"

import { RootLayout } from "@/routes/root"
import { IndexPage } from "@/routes/index"
import { ReplayPage } from "@/routes/replay"
import { AlertsPage } from "@/routes/alerts"
import { DispatchPage } from "@/routes/dispatch"
import { DistrictsPage } from "@/routes/districts"
import { ModelPage } from "@/routes/model"
import { AboutPage } from "@/routes/about"

const rootRoute = createRootRoute({
  component: RootLayout,
})

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: IndexPage,
})

const replayRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/replay",
  component: ReplayPage,
})

const alertsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/alerts",
  component: AlertsPage,
})

const dispatchRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/dispatch",
  component: DispatchPage,
})

const districtsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/districts",
  component: DistrictsPage,
})

const modelRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/model",
  component: ModelPage,
})

const aboutRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/about",
  component: AboutPage,
})

const routeTree = rootRoute.addChildren([
  indexRoute,
  replayRoute,
  alertsRoute,
  dispatchRoute,
  districtsRoute,
  modelRoute,
  aboutRoute,
])

export const router = createRouter({ routeTree })

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router
  }
}
