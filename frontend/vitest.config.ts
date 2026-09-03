// Config de tests aparte del vite.config.ts, y no un bloque `test` dentro
// de el: asi el build de produccion no arrastra tipos ni opciones de
// Vitest. Se reusa la config de Vite (con su alias `@`) via mergeConfig,
// para que los tests resuelvan los imports igual que la app.
import { defineConfig, mergeConfig } from 'vitest/config'
import viteConfig from './vite.config'

export default mergeConfig(
  viteConfig,
  defineConfig({
    // `@vitejs/plugin-react` no toca node_modules, asi que los .tsx de
    // libra-ui los transpila esbuild -- y por defecto usa el runtime
    // CLASICO, que emite `React.createElement` sin que React este
    // importado: "React is not defined" al primer render. Con `automatic`
    // usa el mismo runtime que el resto de la app.
    esbuild: { jsx: 'automatic' },
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: ['./src/test/setup.ts'],
      include: ['src/**/*.test.{ts,tsx}'],
      coverage: {
        provider: 'v8',
        // Trinquete, no meta: sirve para que nadie borre tests, no para medir
        // calidad. Los tests de este SPA son de HUMO a proposito — la logica
        // compartida (Login, tabla, ConfiguracionSmtp, Usuarios) se prueba a
        // fondo en libra-ui, que tiene su propia suite y su propio CI.
        // Medido el 2026-08-02: 81% de lineas; el piso queda 3 puntos abajo.
        thresholds: { lines: 89 },
        reporter: ['text-summary', 'json-summary'],
        // Solo el codigo propio del producto: `libra-ui` tiene su propia
        // suite y su propio CI, medirlo aca contaria dos veces lo mismo.
        include: ['src/**/*.{ts,tsx}'],
        exclude: [
          'src/test/**',          // helpers de test, no codigo de la app
          'src/**/*.d.ts',
          'src/main.tsx',         // solo monta el arbol de React
          'src/components/ui/**', // shadcn/ui: copiado tal cual del upstream
        ],
      },
      server: {
        deps: {
          // `libra-ui` se consume como CODIGO FUENTE (.tsx) desde
          // node_modules -- sus `exports` apuntan a src/. Vitest por
          // defecto no transforma node_modules, asi que ese JSX llegaria
          // sin compilar y todo revienta con "React is not defined".
          // Inlinearlo lo hace pasar por el pipeline de Vite, igual que en
          // el build real del producto.
          inline: ['libra-ui'],
        },
      },
    },
  }),
)
