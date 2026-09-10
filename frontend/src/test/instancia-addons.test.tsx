// El toggle de add-ons en la pantalla de una instancia.
//
// El add-on (`plans.ADDONS`, ej. `mayorista`) es un módulo suelto, fuera de los
// planes. La pantalla lo muestra sólo si el producto tiene add-ons, y el toggle
// pega a `/api/instancias/{slug}/addons/{addon}`. El efecto real (docker exec) lo
// cubre el backend; acá se cuida el cableado de la UI.
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { Instancia } from '../pages/Instancia'

const INSTANCIA = {
  slug: 'acme', nombre: 'ACME SA', container: 'producto-acme',
  domain: 'acme.test', port: 8081, plan: 'pro', estado: 'running',
  iniciado: '', modulos_activos: null, servicio_estado: 'activo', servicio_mensaje: '',
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
}

let fetchMock: ReturnType<typeof vi.fn>

function montar(addons: Record<string, boolean | null>) {
  fetchMock = vi.fn((url: string, opts?: { method?: string }) => {
    const u = String(url)
    if (u.includes('/api/instancias/acme/addons')) {
      // El PUT devuelve el estado nuevo; el GET, el actual.
      if (opts?.method === 'PUT') return Promise.resolve(json({ mayorista: true }))
      return Promise.resolve(json(addons))
    }
    if (u.includes('/api/instancias/acme')) return Promise.resolve(json(INSTANCIA))
    if (u.includes('/api/planes')) return Promise.resolve(json([]))
    return Promise.resolve(json({}))
  })
  vi.stubGlobal('fetch', fetchMock)
  render(
    <MemoryRouter initialEntries={['/instancias/acme']}>
      <Routes>
        <Route path="/instancias/:slug" element={<Instancia />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('add-ons de la instancia', () => {
  it('con add-ons muestra el toggle y lo cambia', async () => {
    const usuario = userEvent.setup()
    montar({ mayorista: false })

    expect(await screen.findByText('mayorista')).toBeInTheDocument()
    const chk = screen.getByRole('checkbox')
    expect(chk).not.toBeChecked()

    await usuario.click(chk)

    const put = fetchMock.mock.calls.find(
      ([u, o]) => String(u).includes('/api/instancias/acme/addons/mayorista') && o?.method === 'PUT',
    )
    expect(put).toBeTruthy()
    // El body lleva `habilitado: true`.
    expect(JSON.parse(String(put![1].body))).toEqual({ habilitado: true })
    // Y el toggle refleja el estado nuevo devuelto por el PUT.
    await waitFor(() => expect(chk).toBeChecked())
  })

  it('sin add-ons no muestra la sección', async () => {
    montar({})
    expect(await screen.findByText('ACME SA')).toBeInTheDocument()
    expect(screen.queryByText('Add-ons')).not.toBeInTheDocument()
  })

  // 🔑 `null` = el motor no pudo leer el estado (contenedor caído, o el producto
  // no exporta `app.database.get_modulos`). Antes llegaba como `false` y la
  // pantalla dibujaba un tilde vacío: eso fue lo que mostró `modo_simple`
  // destildado en una instancia que lo tenía prendido.
  it('estado ilegible: lo dice, y no lo dibuja como apagado', async () => {
    montar({ mayorista: null })

    expect(await screen.findByText('mayorista')).toBeInTheDocument()
    expect(screen.getByText('(no se pudo leer)')).toBeInTheDocument()
  })

  it('estado ilegible: no deja togglear a ciegas', async () => {
    const usuario = userEvent.setup()
    montar({ mayorista: null })

    const chk = await screen.findByRole('checkbox')
    expect(chk).toBeDisabled()

    await usuario.click(chk)

    const put = fetchMock.mock.calls.find(([, o]) => o?.method === 'PUT')
    expect(put).toBeFalsy()
  })

  // El control que hace falta para que los dos de arriba prueben algo: sin él,
  // "mostrar siempre (no se pudo leer)" también pasaría.
  it('apagado de verdad no dice nada raro y sí deja togglear', async () => {
    montar({ mayorista: false })

    expect(await screen.findByText('mayorista')).toBeInTheDocument()
    expect(screen.queryByText('(no se pudo leer)')).not.toBeInTheDocument()
    expect(screen.getByRole('checkbox')).not.toBeDisabled()
  })
})
