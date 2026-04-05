import { createRouter, createWebHistory } from "vue-router"

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "home", component: () => import("./views/HomeView.vue") },
    { path: "/config/memory/self", name: "self", component: () => import("./views/SoulView.vue") },
    { path: "/config/soul", redirect: "/config/memory/self" },
    { path: "/config/memory", redirect: "/config/memory/ltm" },
    { path: "/config/memory/sticky-notes", name: "sticky-notes", component: () => import("./views/StickyNotesView.vue") },
    { path: "/config/memory/ltm", name: "ltm", component: () => import("./views/LtmConfigView.vue") },
    { path: "/config/admins", redirect: "/system" },
    { path: "/config/bot", redirect: "/system" },
    { path: "/config/providers", name: "providers", component: () => import("./views/ProvidersView.vue") },
    { path: "/config/models", name: "models", component: () => import("./views/ModelsView.vue") },
    { path: "/config/prompts", name: "prompts", component: () => import("./views/PromptsView.vue") },
    { path: "/config/plugins", name: "plugins", component: () => import("./views/PluginsView.vue") },
    { path: "/config/skills", name: "skills", component: () => import("./views/SkillsView.vue") },
    { path: "/config/subagents", name: "subagents", component: () => import("./views/SubagentsView.vue") },
    { path: "/sessions", name: "sessions", component: () => import("./views/SessionsView.vue") },
    { path: "/system", name: "system", component: () => import("./views/SystemView.vue") },
    { path: "/logs", name: "logs", component: () => import("./views/LogsView.vue") },
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
})
