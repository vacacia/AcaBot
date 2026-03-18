import { createRouter, createWebHistory } from "vue-router"

import HomeView from "./views/HomeView.vue"
import SoulView from "./views/SoulView.vue"
import MemoryView from "./views/MemoryView.vue"
import BotView from "./views/BotView.vue"
import ModelsView from "./views/ModelsView.vue"
import PromptsView from "./views/PromptsView.vue"
import PluginsView from "./views/PluginsView.vue"
import SkillsView from "./views/SkillsView.vue"
import SubagentsView from "./views/SubagentsView.vue"
import SessionsView from "./views/SessionsView.vue"
import SystemView from "./views/SystemView.vue"

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "home", component: HomeView },
    { path: "/config/soul", name: "soul", component: SoulView },
    { path: "/config/memory", name: "memory", component: MemoryView },
    { path: "/config/bot", name: "bot", component: BotView },
    { path: "/config/models", name: "models", component: ModelsView },
    { path: "/config/prompts", name: "prompts", component: PromptsView },
    { path: "/config/plugins", name: "plugins", component: PluginsView },
    { path: "/config/skills", name: "skills", component: SkillsView },
    { path: "/config/subagents", name: "subagents", component: SubagentsView },
    { path: "/sessions", name: "sessions", component: SessionsView },
    { path: "/system", name: "system", component: SystemView },
  ],
})

