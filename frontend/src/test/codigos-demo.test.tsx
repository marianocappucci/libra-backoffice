// La pestaña «Demo»: emitir, listar y revocar códigos de acceso.
//
// Toda la pantalla está construida alrededor de un hecho del motor: **el código
// se ve una sola vez**. `libraauth` guarda su sha256 y el listado devuelve sólo
// el prefijo de 4 caracteres, así que si el recuadro del alta desaparece antes
// de que alguien lo copie, hay que emitir otro. Eso es lo que fijan la mitad de
// estos tests.
//
// La otra mitad es el par que hace útil a todo el archivo: una instancia demo
// contesta el listado, y una que no es demo contesta **404** porque no monta el
// router. Sin el segundo caso, un proxy que devolviera lo mismo para cualquier
// instancia pasaría en verde — y ahí es donde se le muestran los códigos de la
// demo a quien abrió la ficha de un cliente.
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import App from '../App'
import { AuthProvider } from '../auth'

let fetchMock: ReturnType<typeof vi.fn>

beforeEach(() => {
  fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)
})

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status, headers: { 'content-type': 'application/json' },
  })
}

const INSTANCIA = {
  slug: 'acme', nombre: 'ACME SA', container: 'producto-acme',
  domain: 'acme.test', port: 8081, plan: 'pro', estado: 'running',
  iniciado: '', modulos_activos: null,
  servicio_estado: 'activo', servicio_mensaje: '',
}

const VIGENTE = {
  id: 1, prefijo: 'H7KQ', etiqueta: 'Estudio Pérez', emitido_por: 'superadmin',
  creado_at: '2026-08-18T10:00:00', expires_at: '2026-08-25T10:00:00',
  ultimo_uso: null, usos: 0, usos_max: 10, estado: 'vigente',
}

const VENCIDO = {
  ...VIGENTE, id: 2, prefijo: '9MRT', etiqueta: 'Feria de octubre',
  usos: 4, estado: 'vencido',
}

type Init = { method?: string } | undefined

function conSesion(rutas: Record<string, (init: Init) => Promise<Response>> = {}) {
  fetchMock.mockImplementation((url: string, init: Init) => {
    const u = String(url)
    const metodo = init?.method ?? 'GET'
    const propia = rutas[`${metodo} ${u}`] ?? rutas[u]
    if (propia) return propia(init)

    if (u.includes('/api/me')) return Promise.resolve(json({ username: 'superadmin' }))
    if (u.includes('/demo-codigos')) return Promise.resolve(json({ codigos: [] }))
    if (u.includes('/api/instancias/')) return Promise.resolve(json(INSTANCIA))
    if (u.includes('/api/planes')) return Promise.resolve(json([]))
    return Promise.resolve(json([]))
  })
}

const usuario = () => userEvent.setup({ pointerEventsCheck: 0 })

function cuerpoDe(llamada: unknown[]): Record<string, unknown> {
  return JSON.parse(String((llamada[1] as { body?: string }).body))
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

async function irADemo(u: ReturnType<typeof usuario>) {
  const nav = await screen.findByRole('navigation', { name: /secciones de la instancia/i })
  await u.click(within(nav).getByRole('button', { name: /demo/i }))
}

describe('la pestaña Demo', () => {
  it('le pega a la URL de ESA instancia', async () => {
    // La diferencia entre emitirle un código a la demo y a otra cosa.
    conSesion()
    montar('/instancias/acme')
    await irADemo(usuario())

    await waitFor(() => expect(
      fetchMock.mock.calls.some((c) =>
        String(c[0]).includes('/api/instancias/acme/demo-codigos'))).toBe(true))
  })

  it('sin códigos avisa que nadie puede entrar', async () => {
    // Un "no hay nada" a secas se lee como que falta cargar algo. Lo que
    // significa de verdad es que la demo está cerrada.
    conSesion()
    montar('/instancias/acme')
    await irADemo(usuario())

    expect(await screen.findByText(/nadie puede entrar a la demo/i)).toBeInTheDocument()
  })

  it('lista los emitidos por prefijo y estado', async () => {
    conSesion({
      '/api/instancias/acme/demo-codigos': () =>
        Promise.resolve(json({ codigos: [VIGENTE, VENCIDO] })),
    })
    montar('/instancias/acme')
    await irADemo(usuario())

    expect(await screen.findByText('H7KQ…')).toBeInTheDocument()
    expect(screen.getByText('Estudio Pérez')).toBeInTheDocument()
    expect(screen.getByText('vencido')).toBeInTheDocument()
    expect(screen.getByText('4 / 10')).toBeInTheDocument()
  })

  it('emite con los valores del formulario', async () => {
    conSesion({
      'POST /api/instancias/acme/demo-codigos': () =>
        Promise.resolve(json({ ...VIGENTE, codigo: 'H7KQ-9MRT-2XVB' }, 201)),
    })
    montar('/instancias/acme')
    const u = usuario()
    await irADemo(u)

    await u.type(await screen.findByLabelText(/para quién/i), 'Estudio Pérez')
    await u.clear(screen.getByLabelText(/^días$/i))
    await u.type(screen.getByLabelText(/^días$/i), '3')
    await u.click(screen.getByRole('button', { name: /emitir/i }))

    await waitFor(() => {
      const post = fetchMock.mock.calls.find((c) =>
        (c[1] as Init)?.method === 'POST' && String(c[0]).includes('/demo-codigos'))
      expect(post).toBeTruthy()
      expect(cuerpoDe(post!)).toEqual({
        etiqueta: 'Estudio Pérez', dias: 3, usos_max: 10,
      })
    })
  })

  it('🔴 muestra el código emitido y avisa que es la única vez', async () => {
    // Es el corazón de la pantalla: el motor guarda el hash, así que este
    // recuadro es la única oportunidad de copiarlo. Si desapareciera solo,
    // habría que emitir otro.
    conSesion({
      'POST /api/instancias/acme/demo-codigos': () =>
        Promise.resolve(json({ ...VIGENTE, codigo: 'H7KQ-9MRT-2XVB' }, 201)),
    })
    montar('/instancias/acme')
    const u = usuario()
    await irADemo(u)
    await u.click(await screen.findByRole('button', { name: /emitir/i }))

    expect(await screen.findByText('H7KQ-9MRT-2XVB')).toBeInTheDocument()
    expect(screen.getByText(/única vez que se muestra/i)).toBeInTheDocument()
  })

  it('el recuadro del código no se cierra solo al recargar la lista', async () => {
    // Sin esto, un `releer()` que limpiara el estado haría desaparecer el
    // código antes de que nadie lo copie, y el test de arriba pasaría igual
    // porque mira el instante siguiente al click.
    conSesion({
      'POST /api/instancias/acme/demo-codigos': () =>
        Promise.resolve(json({ ...VIGENTE, codigo: 'H7KQ-9MRT-2XVB' }, 201)),
      '/api/instancias/acme/demo-codigos': () =>
        Promise.resolve(json({ codigos: [VIGENTE] })),
    })
    montar('/instancias/acme')
    const u = usuario()
    await irADemo(u)
    await u.click(await screen.findByRole('button', { name: /emitir/i }))
    // La lista ya se releyó: aparece la fila nueva.
    expect(await screen.findByText('H7KQ…')).toBeInTheDocument()

    expect(screen.getByText('H7KQ-9MRT-2XVB')).toBeInTheDocument()
  })

  it('revoca sólo los vigentes', async () => {
    // Revocar un vencido no cambia nada, y el botón sugeriría que sí.
    conSesion({
      '/api/instancias/acme/demo-codigos': () =>
        Promise.resolve(json({ codigos: [VIGENTE, VENCIDO] })),
      'DELETE /api/instancias/acme/demo-codigos/1': () =>
        Promise.resolve(json({ ...VIGENTE, estado: 'revocado' })),
    })
    montar('/instancias/acme')
    const u = usuario()
    await irADemo(u)
    await screen.findByText('H7KQ…')

    const botones = screen.getAllByRole('button', { name: /revocar/i })
    expect(botones).toHaveLength(1)

    await u.click(botones[0])
    await waitFor(() => expect(
      fetchMock.mock.calls.some((c) =>
        (c[1] as Init)?.method === 'DELETE'
        && String(c[0]).endsWith('/demo-codigos/1'))).toBe(true))
  })

  it('🔴 en una instancia que no es demo lo dice, en vez de un ABM vacío', async () => {
    // La instancia contesta 404 porque no monta el router. Un listado vacío se
    // leería como "todavía no se emitió ninguno" e invitaría a emitir uno que
    // no va a servir para nada.
    conSesion({
      '/api/instancias/acme/demo-codigos': () =>
        Promise.resolve(json({ detail: 'Not Found' }, 404)),
    })
    montar('/instancias/acme')
    await irADemo(usuario())

    expect(await screen.findByText(/no es una demo/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /emitir/i })).not.toBeInTheDocument()
  })

  it('un error del servidor se muestra, no se traga', async () => {
    conSesion({
      '/api/instancias/acme/demo-codigos': () =>
        Promise.resolve(json({ detail: "La instancia 'acme' no responde" }, 502)),
    })
    montar('/instancias/acme')
    await irADemo(usuario())

    expect(await screen.findByText(/no responde/i)).toBeInTheDocument()
  })
})
