// Guard: una pantalla no agrega relleno propio arriba de lo que ya le da el Layout (ADR-040, libra-ui v0.129.0).
//
// 🔴 **Lee los FUENTES, no el DOM.** Una pantalla con un `p-6` de más no se rompe: deja «un espacio vacío arriba» y el título queda más abajo
// que el nombre de la app (pedido del dueño, 2026-10-08). Y vuelve sola: la próxima pantalla copia el `<div className="p-6">` de la de al lado.
// El motor vive en `libra-ui/auditoria-de-relleno` y tiene sus propios tests allá.
//
// Las pantallas que se dibujan FUERA del Layout necesitan su propio relleno y van como excepciones, con motivo.
import { describe, expect, it } from 'vitest'
import { join } from 'node:path'
import { auditarRelleno, describirInfracciones, describirSobrantes } from 'libra-ui/auditoria-de-relleno'

const SRC = join(process.cwd(), 'src')

const EXCEPCIONES: Record<string, string> = {}

describe('las pantallas no agregan relleno propio', () => {
  const r = auditarRelleno(SRC, { excepciones: EXCEPCIONES })

  it('🔴 el control — el guard midió algo (un parser que devuelve cero sería un falso verde)', () => {
    expect(r.archivos).toBeGreaterThan(0)
    expect(r.pantallas).toBeGreaterThan(0)
    expect(r.raices).toBeGreaterThan(0)
  })

  it('🔴 ninguna pantalla agrega p-N, py-N, pt-N ni mt-N en su elemento raíz', () => {
    expect(describirInfracciones(r.infracciones)).toEqual([])
  })

  it('las excepciones siguen haciendo falta (si una ya no, sacarla de la lista)', () => {
    expect(describirSobrantes(r.sobrantes)).toEqual([])
  })
})
