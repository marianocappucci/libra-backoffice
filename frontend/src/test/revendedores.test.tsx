// La consola de revendedores en pantalla. Las reglas viven en el backend (`test_revendedores.py`); acá se prueba lo que la pantalla
// tiene que hacer: no ofrecer el bloqueo sin confirmar, decir qué pasó con cada instancia y entrar por la pantalla que corresponde.
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import App from '../App'
import { AuthProvider } from '../auth'

const REVENDEDOR = {
  id: 'r1', nombre: 'Distribuidora Sur', contacto: 'ventas@sur.test', notas: '', productos: ['ventalibra'],
  instancias: [{ producto: 'ventalibra', slug: 'acme' }], suspendidas: [], estado: 'activo', mensaje: '',
  historial: [{ cuando: '2026-11-01T12:00:00+00:00', quien: 'superadmin', accion: 'alta', detalle: '' }],
}
const CATALOGO = {
  productos: [
    {
      slug: 'ventalibra', nombre: 'VentaLibra', alcanzable: true, detalle: '',
      instancias: [
        { slug: 'acme', nombre: 'ACME', domain: '', plan: '', estado: 'running', servicio_estado: 'activo', revendedor: 'Distribuidora Sur' },
        { slug: 'beta', nombre: 'Beta', domain: '', plan: '', estado: 'running', servicio_estado: 'activo', revendedor: '' },
      ],
    },
    { slug: 'libracargo', nombre: 'LibraCargo', alcanzable: false, detalle: 'no contesta (ConnectError)', instancias: [] },
  ],
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
}

let llamadas: { metodo: string; url: string; cuerpo: unknown }[]

function conSesion(extra: Record<string, () => Response> = {}, features = ['revendedores']) {
  llamadas = []
  vi.stubGlobal('fetch', vi.fn((url: string, init?: { method?: string; body?: string }) => {
    const metodo = init?.method ?? 'GET'
    const u = String(url).split('?')[0]
    llamadas.push({ metodo, url: u, cuerpo: init?.body ? JSON.parse(init.body) : undefined })
    const ruta = extra[`${metodo} ${u}`]
    if (ruta) return Promise.resolve(ruta())
    if (u === '/api/me') return Promise.resolve(json({ username: 'superadmin', features }))
    if (u === '/api/revendedores/catalogo') return Promise.resolve(json(CATALOGO))
    if (u === '/api/revendedores') return Promise.resolve(json({ revendedores: [REVENDEDOR] }))
    if (u === '/api/revendedores/r1') return Promise.resolve(json(REVENDEDOR))
    return Promise.resolve(json([]))
  }))
}

function montar(ruta: string) {
  return render(
    <MemoryRouter initialEntries={[ruta]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
}

const usuario = () => userEvent.setup({ pointerEventsCheck: 0 })

beforeEach(() => vi.unstubAllGlobals())

describe('la consola', () => {
  it('entra por Revendedores y no muestra lo que no tiene', async () => {
    conSesion()
    montar('/instancias')
    expect(await screen.findByRole('heading', { name: 'Revendedores' })).toBeInTheDocument()
    expect(await screen.findByRole('link', { name: 'Distribuidora Sur' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Salud' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Instancias' })).not.toBeInTheDocument()
  })

  it('el alta manda los productos elegidos', async () => {
    conSesion({ 'POST /api/revendedores': () => json(REVENDEDOR, 201) })
    montar('/revendedores')
    const u = usuario()
    await u.type(await screen.findByLabelText('Nombre'), 'Nuevo')
    await u.click(await screen.findByRole('checkbox', { name: 'VentaLibra' }))
    await u.click(screen.getByRole('button', { name: /agregar revendedor/i }))
    await waitFor(() => expect(llamadas.find((l) => l.metodo === 'POST')?.cuerpo).toEqual({
      nombre: 'Nuevo', contacto: '', notas: '', productos: ['ventalibra'],
    }))
  })
})

describe('la ficha', () => {
  it('avisa si un backoffice no contesta y ofrece sólo instancias sin dueño de lo habilitado', async () => {
    conSesion()
    montar('/revendedores/r1')
    expect(await screen.findByText(/el backoffice de libracargo: no contesta/i)).toBeInTheDocument()
    const u = usuario()
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Asignar instancia' })).toBeEnabled())
    await u.click(screen.getByRole('combobox', { name: 'Asignar instancia' }))
    expect(await screen.findByText('VentaLibra: Beta')).toBeInTheDocument()
    expect(screen.queryByText(/VentaLibra: ACME/)).not.toBeInTheDocument()
  })

  it('no deja bloquear sin escribir el nombre y un mensaje', async () => {
    conSesion()
    montar('/revendedores/r1')
    const u = usuario()
    await u.click(await screen.findByRole('button', { name: /bloquear revendedor/i }))
    const suspender = screen.getByRole('button', { name: /suspender 1 instancia/i })
    expect(suspender).toBeDisabled()
    await u.type(screen.getByLabelText(/mensaje que ven/i), 'Cortado')
    await u.type(screen.getByLabelText(/para confirmar/i), 'Distribuidora')
    expect(suspender).toBeDisabled()
    await u.type(screen.getByLabelText(/para confirmar/i), ' Sur')
    expect(suspender).toBeEnabled()
  })

  it('tras bloquear dice qué pasó con cada instancia, y que un error se reintenta', async () => {
    conSesion({
      'POST /api/revendedores/r1/bloquear': () => json({
        revendedor: { ...REVENDEDOR, estado: 'bloqueado', mensaje: 'Cortado' },
        resultados: [
          { producto: 'ventalibra', slug: 'acme', resultado: 'fallo', detalle: 'no contesta' },
          { producto: 'ventalibra', slug: 'moroso', resultado: 'ya_estaba_suspendida', detalle: '' },
        ],
      }),
    })
    montar('/revendedores/r1')
    const u = usuario()
    await u.click(await screen.findByRole('button', { name: /bloquear revendedor/i }))
    await u.type(screen.getByLabelText(/mensaje que ven/i), 'Cortado')
    await u.type(screen.getByLabelText(/para confirmar/i), 'Distribuidora Sur')
    await u.click(screen.getByRole('button', { name: /suspender 1 instancia/i }))
    expect(await screen.findByText(/no se pudo: no contesta/i)).toBeInTheDocument()
    expect(screen.getByText(/ya estaba suspendida: al desbloquear no vuelve/i)).toBeInTheDocument()
    expect(screen.getByText(/repetir la acción sigue desde donde quedó/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^desbloquear$/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /reintentar el bloqueo/i })).toBeInTheDocument()
  })

  it('bloqueado no ofrece asignar, y dice que sólo vuelve lo que suspendió la consola', async () => {
    conSesion({ 'GET /api/revendedores/r1': () => json({ ...REVENDEDOR, estado: 'bloqueado', mensaje: 'Cortado' }) })
    montar('/revendedores/r1')
    expect(await screen.findByText(/reactiva sólo las instancias que suspendió la consola/i)).toBeInTheDocument()
    expect(screen.queryByRole('combobox', { name: 'Asignar instancia' })).not.toBeInTheDocument()
  })

  it('una instancia suspendida por la consola no se puede quitar', async () => {
    conSesion({
      'GET /api/revendedores/r1': () => json({ ...REVENDEDOR, estado: 'bloqueado', suspendidas: REVENDEDOR.instancias }),
    })
    montar('/revendedores/r1')
    expect(await screen.findByText('Suspendida por la consola')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Quitar ventalibra acme' })).toBeDisabled()
  })
})

describe('un backoffice de producto', () => {
  it('no muestra Revendedores', async () => {
    conSesion({ 'GET /api/instancias': () => json({ instancias: [] }) }, ['instancias', 'salud'])
    montar('/instancias')
    expect(await screen.findByRole('link', { name: 'Salud' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Revendedores' })).not.toBeInTheDocument()
  })
})

describe('la credencial del panel', () => {
  it('se muestra una sola vez y avisa si ya hay una', async () => {
    conSesion({
      'GET /api/revendedores/r1/credencial-panel': () => json({ tiene: false }),
      'POST /api/revendedores/r1/credencial-panel': () => json({ credencial: 'la-credencial-de-prueba' }),
    })
    montar('/revendedores/r1')
    const u = usuario()
    expect(await screen.findByText('Todavía no tiene credencial.')).toBeInTheDocument()
    await u.click(screen.getByRole('button', { name: 'Generar credencial' }))
    expect(await screen.findByText('la-credencial-de-prueba')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Generar otra' })).toBeInTheDocument()
  })
})
