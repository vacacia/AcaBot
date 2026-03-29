import { createRouter, createWebHistory } from "vue-router"

import HomeView from "./views/HomeView.vue"
import SoulView from "./views/SoulView.vue"
import MemoryView from "./views/MemoryView.vue"
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
    { path: "/config/soul", name: "soul", component: SoulView },
    { path: "/config/memory", name: "memory", component: MemoryView },
    { path: "/config/admins", redirect: "/system" },
    { path: "/config/bot", redirect: "/system" },
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
