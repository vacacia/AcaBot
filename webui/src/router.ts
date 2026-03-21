import { createRouter, createWebHistory } from "vue-router"

import HomeView from "./views/HomeView.vue"
import GlassEditorialView from "./views/GlassEditorialView.vue"
import GlassInstrumentView from "./views/GlassInstrumentView.vue"
import GlassLabView from "./views/GlassLabView.vue"
import MaterialConsoleView from "./views/MaterialConsoleView.vue"
import MaterialDarkStudyView from "./views/MaterialDarkStudyView.vue"
import MaterialFrostStudyView from "./views/MaterialFrostStudyView.vue"
import SoulView from "./views/SoulView.vue"
import MemoryView from "./views/MemoryView.vue"
import AdminsView from "./views/AdminsView.vue"
import ProvidersView from "./views/ProvidersView.vue"
import ModelsView from "./views/ModelsView.vue"
import PromptsView from "./views/PromptsView.vue"
import PluginsView from "./views/PluginsView.vue"
import SkillsView from "./views/SkillsView.vue"
import SubagentsView from "./views/SubagentsView.vue"
import SessionsView from "./views/SessionsView.vue"
import SystemView from "./views/SystemView.vue"
import LogsView from "./views/LogsView.vue"

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "home", component: HomeView },
    { path: "/preview/glass-lab", redirect: "/preview/glass-lab/graphite" },
    {
      path: "/preview/glass-lab/graphite",
      name: "glass-lab-graphite",
      component: GlassLabView,
      props: { palette: "graphite" },
    },
    {
      path: "/preview/glass-lab/verdigris",
      name: "glass-lab-verdigris",
      component: GlassLabView,
      props: { palette: "verdigris" },
    },
    {
      path: "/preview/glass-lab/brass",
      name: "glass-lab-brass",
      component: GlassLabView,
      props: { palette: "brass" },
    },
    {
      path: "/preview/glass-lab/bordeaux",
      name: "glass-lab-bordeaux",
      component: GlassLabView,
      props: { palette: "bordeaux" },
    },
    {
      path: "/preview/glass-lab/editorial-graphite",
      name: "glass-editorial-graphite",
      component: GlassEditorialView,
    },
    {
      path: "/preview/glass-lab/instrument-brass",
      name: "glass-instrument-brass",
      component: GlassInstrumentView,
    },
    { path: "/preview/material-console", redirect: "/preview/material-console/cold-graphite" },
    {
      path: "/preview/material-console/cold-graphite",
      name: "material-console-cold-graphite",
      component: MaterialConsoleView,
      props: { variant: "cold-graphite" },
    },
    {
      path: "/preview/material-console/warm-mineral",
      name: "material-console-warm-mineral",
      component: MaterialConsoleView,
      props: { variant: "warm-mineral" },
    },
    {
      path: "/preview/material-console/deep-flagship",
      name: "material-console-deep-flagship",
      component: MaterialConsoleView,
      props: { variant: "deep-flagship" },
    },
    { path: "/preview/material-dark", redirect: "/preview/material-dark/cold-black-titanium" },
    {
      path: "/preview/material-dark/smoked-graphite",
      name: "material-dark-smoked-graphite",
      component: MaterialDarkStudyView,
      props: { variant: "smoked-graphite" },
    },
    {
      path: "/preview/material-dark/mineral-dusk",
      name: "material-dark-mineral-dusk",
      component: MaterialDarkStudyView,
      props: { variant: "mineral-dusk" },
    },
    {
      path: "/preview/material-dark/slate-flagship",
      name: "material-dark-slate-flagship",
      component: MaterialDarkStudyView,
      props: { variant: "slate-flagship" },
    },
    {
      path: "/preview/material-dark/monochrome-graphite",
      name: "material-dark-monochrome-graphite",
      component: MaterialDarkStudyView,
      props: { variant: "monochrome-graphite" },
    },
    {
      path: "/preview/material-dark/cold-black-titanium",
      name: "material-dark-cold-black-titanium",
      component: MaterialDarkStudyView,
      props: { variant: "cold-black-titanium" },
    },
    {
      path: "/preview/material-dark/warm-black-ore",
      name: "material-dark-warm-black-ore",
      component: MaterialDarkStudyView,
      props: { variant: "warm-black-ore" },
    },
    {
      path: "/preview/material-dark/blue-black-flagship",
      name: "material-dark-blue-black-flagship",
      component: MaterialDarkStudyView,
      props: { variant: "blue-black-flagship" },
    },
    { path: "/preview/material-frost", redirect: "/preview/material-frost/smoke/glass/accent" },
    {
      path: "/preview/material-frost/:base/:material/:coverage",
      name: "material-frost-study",
      component: MaterialFrostStudyView,
      props: (route) => ({
        base: Array.isArray(route.params.base) ? route.params.base[0] : route.params.base,
        material: Array.isArray(route.params.material) ? route.params.material[0] : route.params.material,
        coverage: Array.isArray(route.params.coverage) ? route.params.coverage[0] : route.params.coverage,
      }),
    },
    { path: "/config/soul", name: "soul", component: SoulView },
    { path: "/config/memory", name: "memory", component: MemoryView },
    { path: "/config/admins", name: "admins", component: AdminsView },
    { path: "/config/bot", redirect: "/config/admins" },
    { path: "/config/providers", name: "providers", component: ProvidersView },
    { path: "/config/models", name: "models", component: ModelsView },
    { path: "/config/prompts", name: "prompts", component: PromptsView },
    { path: "/config/plugins", name: "plugins", component: PluginsView },
    { path: "/config/skills", name: "skills", component: SkillsView },
    { path: "/config/subagents", name: "subagents", component: SubagentsView },
    { path: "/sessions", name: "sessions", component: SessionsView },
    { path: "/system", name: "system", component: SystemView },
    { path: "/logs", name: "logs", component: LogsView },
  ],
})
