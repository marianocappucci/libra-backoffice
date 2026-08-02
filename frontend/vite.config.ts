import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Toda la API del backoffice cuelga de `/api` y `/health`, así que el proxy de
// dev es mucho más simple que el de los productos (que tienen una docena de
// prefijos y por eso necesitan la regex con `(?:/|$)` para no secuestrar rutas
// de la SPA que empiezan igual — ver el comentario largo en el vite.config.ts
// de Gestiolibra y el incidente de VentaLibra del 2026-07-28).
//
// Acá `/api` no colisiona con ninguna ruta de la SPA porque las rutas de la
// SPA son `/instancias/...` y `/salud`. Igual se usa la forma con regex, para
// que agregar una ruta como `/apitest` no se vuelva un problema silencioso.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      // Lo que hace que `libra-ui` funcione: sus componentes importan los
      // primitivos de shadcn como `@/components/ui/...`, y Vite aplica este
      // alias también al código que viene de `node_modules`. Así cada
      // consumidor compila libra-ui contra SUS primitivos shadcn, que es
      // justo el punto de que shadcn se distribuya como código copiado.
      '@': new URL('./src', import.meta.url).pathname,
    },
  },
  server: {
    proxy: {
      '^/api(?:/|$)': { target: 'http://localhost:8000', changeOrigin: true },
      '^/health(?:/|$)': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
})
