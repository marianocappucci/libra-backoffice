// El registro de errores del navegador, cableado de verdad (ADR-053 de libra-ui, ADR-045 de libracore).
// El comportamiento fino lo prueba libra-ui; acá se prueba lo que es de este repo: que el `<ErrorBoundary>` se
// resuelve con los `Card`/`Button` de ESTE frontend, y que un error de render llega a `/api/errores-cliente`.
import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ErrorBoundary } from 'libra-ui/ErrorBoundary'
import {
  _reiniciarReporteDeErrores,
  ENDPOINT_ERRORES,
  instalarReporteDeErrores,
} from 'libra-ui/errores-del-navegador'

function Roto(): never {
  throw new Error('se rompio el render')
}

describe('el registro de errores del navegador', () => {
  let mandado: { url: string; cuerpo: string }[]

  beforeEach(() => {
    mandado = []
    Object.defineProperty(navigator, 'sendBeacon', {
      configurable: true,
      value: (url: string, blob: Blob) => {
        void blob.text().then((cuerpo) => mandado.push({ url, cuerpo }))
        return true
      },
    })
    // React escribe el error de render en la consola; no es ruido útil acá.
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  afterEach(() => {
    _reiniciarReporteDeErrores()
  })

  it('una pantalla que revienta muestra «Algo falló» y no un blanco', () => {
    render(<ErrorBoundary><Roto /></ErrorBoundary>)
    expect(screen.getByRole('alert')).toHaveTextContent('Algo falló.')
    expect(screen.getByRole('button', { name: 'Recargar' })).toBeInTheDocument()
    // Nunca el mensaje del error: puede traer datos.
    expect(screen.queryByText(/se rompio el render/)).not.toBeInTheDocument()
  })

  it('un error de render se reporta a /api/errores-cliente', async () => {
    instalarReporteDeErrores()
    render(<ErrorBoundary><Roto /></ErrorBoundary>)
    await vi.waitFor(() => expect(mandado).toHaveLength(1))
    expect(mandado[0].url).toBe(ENDPOINT_ERRORES)
    expect(mandado[0].url).toBe('/api/errores-cliente')
    expect(JSON.parse(mandado[0].cuerpo)).toMatchObject({ tipo: 'render', mensaje: 'se rompio el render' })
  })

  it('sin instalarReporteDeErrores no se manda nada', async () => {
    render(<ErrorBoundary><Roto /></ErrorBoundary>)
    await new Promise((r) => setTimeout(r, 30))
    expect(mandado).toHaveLength(0)
  })
})
