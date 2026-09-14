// La pestaña Usuarios de una instancia, después de adoptar el contrato único
// de libraauth (ADR-018) — ver `backend/libra_backoffice/routers/config_instancia.py`
// y `Instancia.tsx`.
//
// El ABM en sí (alta/edición/grilla) ya lo prueban los 68 tests de libra-ui.
// Acá se prueba el cableado de ESTE repo: que los roles de `/api/salud`
// (`USERS_ROLES`) lleguen al `Select` de la pantalla, que el botón Eliminar
// esté visible (`permitirEliminar`), y que pegue en el proxy nuevo
// (`DELETE .../usuarios/{id}`, `PUT .../usuarios/{id}/password`).
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { Instancia } from '../pages/Instancia'

const INSTANCIA = {
  slug: 'acme', nombre: 'ACME SA', container: 'producto-acme',
  domain: 'acme.test', port: 8081, plan: 'pro', estado: 'running',
  iniciado: '', modulos_activos: null, servicio_estado: 'activo', servicio_mensaje: '',
}

const USUARIOS = [
  { id: '1', username: 'ana', name: 'Ana Pérez', role: 'operador', active: true, email: 'ana@acme.test' },
]

// Vocabulario de Contalibra/Restolibra — distinto del default
// (`staff`/`admin`) a propósito: si esto aparece en el `Select`, es porque
// vino de `/api/salud` y no del default de `Usuarios` (libra-ui).
const ROLES = [
  { value: 'admin', label: 'Admin' },
  { value: 'operador', label: 'Operador' },
  { value: 'cajero', label: 'Cajero' },
]

function json(body: unknown, status = 200) {
  if (status === 204) return new Response(null, { status })
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
}

let fetchMock: ReturnType<typeof vi.fn>

function montar() {
  fetchMock = vi.fn((url: string, opts?: { method?: string }) => {
    const u = String(url)
    const metodo = opts?.method ?? 'GET'
    if (u.endsWith('/api/instancias/acme/usuarios') && metodo === 'GET') {
      return Promise.resolve(json(USUARIOS))
    }
    if (u.includes('/api/instancias/acme/usuarios/') && u.endsWith('/password') && metodo === 'PUT') {
      return Promise.resolve(json(null, 204))
    }
    if (u.includes('/api/instancias/acme/usuarios/') && metodo === 'DELETE') {
      return Promise.resolve(json(null, 204))
    }
    if (u.endsWith('/api/instancias/acme')) return Promise.resolve(json(INSTANCIA))
    if (u.endsWith('/api/planes')) return Promise.resolve(json([]))
    if (u.includes('/addons')) return Promise.resolve(json({}))
    if (u.includes('/api/salud')) {
      return Promise.resolve(json({
        producto: { slug: 'contalibra', nombre: 'Contalibra' },
        features: ['instancias', 'usuarios', 'salud'],
        usuarios_roles: ROLES,
        backoffice: { version: 'x', commit: 'y', arrancado: '', uptime_segundos: 1 },
        instancias: [],
      }))
    }
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

const usuario = () => userEvent.setup({ pointerEventsCheck: 0 })

async function irAUsuarios(u: ReturnType<typeof usuario>) {
  const nav = await screen.findByRole('navigation', { name: /secciones de la instancia/i })
  await u.click(within(nav).getByRole('button', { name: /^usuarios$/i }))
}

describe('roles de la pestaña Usuarios', () => {
  it('el Select de rol muestra los roles de USERS_ROLES (vía /api/salud), no el default', async () => {
    const u = usuario()
    montar()
    await irAUsuarios(u)

    await u.click(await screen.findByRole('button', { name: /nuevo usuario/i }))
    const dialogo = screen.getByRole('dialog')
    await u.click(within(dialogo).getByRole('combobox', { name: /^rol$/i }))

    for (const rol of ROLES) {
      expect(await screen.findByRole('option', { name: rol.label })).toBeInTheDocument()
    }
    // Y el default de libra-ui (Staff) NO aparece: si apareciera, `roles` no
    // estaría llegando desde `/api/salud`.
    expect(screen.queryByRole('option', { name: 'Staff' })).not.toBeInTheDocument()
  })
})

describe('borrado de usuarios (permitirEliminar)', () => {
  it('el botón Eliminar está visible y pega en el DELETE del proxy nuevo', async () => {
    const u = usuario()
    montar()
    await irAUsuarios(u)

    await screen.findByText('Ana Pérez')
    await u.click(screen.getByRole('button', { name: /eliminar ana pérez/i }))

    const confirmacion = screen.getByRole('alertdialog')
    await u.click(within(confirmacion).getByRole('button', { name: /^eliminar$/i }))

    await waitFor(() => {
      const del = fetchMock.mock.calls.find(
        ([url, opts]) => String(url).endsWith('/api/instancias/acme/usuarios/1')
          && (opts as { method?: string } | undefined)?.method === 'DELETE',
      )
      expect(del).toBeTruthy()
    })
  })
})

describe('cambio de contraseña de otro usuario', () => {
  it('pega en PUT .../usuarios/{id}/password', async () => {
    const u = usuario()
    montar()
    await irAUsuarios(u)

    await screen.findByText('Ana Pérez')
    await u.click(screen.getByRole('button', { name: /cambiar contraseña de ana pérez/i }))

    const dialogo = screen.getByRole('dialog')
    await u.type(within(dialogo).getByLabelText(/contraseña nueva/i), 'una-clave-nueva')
    await u.click(within(dialogo).getByRole('button', { name: /^cambiar$/i }))

    await waitFor(() => {
      const put = fetchMock.mock.calls.find(
        ([url, opts]) => String(url).endsWith('/api/instancias/acme/usuarios/1/password')
          && (opts as { method?: string } | undefined)?.method === 'PUT',
      )
      expect(put).toBeTruthy()
      const cuerpo = JSON.parse(String((put![1] as { body?: string }).body))
      expect(cuerpo).toEqual({ password: 'una-clave-nueva' })
    })
  })
})
