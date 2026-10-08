// Guard: todo desplegable de DATOS se busca escribiendo (ADR-039, libra-ui v0.129.0).
//
// 🔴 **Lee los FUENTES, no el DOM.** Lo que hay que impedir no es que una pantalla se rompa (ninguna se rompe con un `<Select>` de 300 clientes:
// se ve bien con 9) sino que vuelva a nacer un desplegable de datos que no se puede buscar. Eso se ve en el JSX, no en un render. El motor vive
// en `libra-ui/auditoria-de-selects` y tiene sus propios tests allá.
//
// Una lista que sale de una constante del código y es corta de verdad se marca con `select-cerrado: <motivo>` en el renglón del `<Select>` o en
// los tres de arriba.
import { describe, expect, it } from 'vitest'
import { join } from 'node:path'
import { auditarSelects, describirInfracciones } from 'libra-ui/auditoria-de-selects'

const SRC = join(process.cwd(), 'src')

describe('los desplegables de datos se buscan escribiendo', () => {
  const r = auditarSelects(SRC)

  it('🔴 el control — el guard midió algo (un parser que devuelve cero sería un falso verde)', () => {
    expect(r.archivos).toBeGreaterThan(0)
    expect(r.desplegables).toBeGreaterThan(0)
  })

  it('🔴 ningún desplegable de datos es un Select sin búsqueda', () => {
    expect(describirInfracciones(r.infracciones)).toEqual([])
  })
})
