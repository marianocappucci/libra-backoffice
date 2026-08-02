// Humo del backoffice: que la app monte, que el guard de rutas haga lo que
// dice, y que las pantallas por instancia le peguen a la URL de ESA instancia.
//
// El Login, la tabla, `ConfiguracionSmtp` y `Usuarios` vienen de libra-ui, que
// tiene sus propios 68 tests. Acá se prueba el cableado de este repo, y sobre
// todo lo único que no puede probar libra-ui: que el `basePath` que se le pasa
// lleve el slug correcto. Es la diferencia entre configurarle el correo al
// cliente correcto y al equivocado.
import { render, screen, waitFor } from '@testing-library/react'
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
    status,
    headers: { 'content-type': 'application/json' },
  })
}

const INSTANCIA = {
  slug: 'acme', nombre: 'ACME SA', container: 'producto-acme',
  domain: 'acme.test', port: 8081, plan: 'pro', estado: 'running',
  iniciado: '', modulos_activos: null,
}

const SMTP = {
  origen: 'entorno', host: '', port: 587, user: '', from_email: '', from_name: '',
  password_definida: false, password_indescifrable: false, configurado: false,
}

/** Sin sesión: `/api/me` responde 401, como con la cookie vencida. */
function sinSesion() {
  fetchMock.mockImplementation(() => Promise.resolve(json({ detail: 'No autenticado' }, 401)))
}

function conSesion() {
  fetchMock.mockImplementation((url: string) => {
    const u = String(url)
    if (u.includes('/api/me')) return Promise.resolve(json({ username: 'superadmin' }))
    if (u.endsWith('/api/instancias')) return Promise.resolve(json({ instancias: [INSTANCIA] }))
    if (u.includes('/smtp')) return Promise.resolve(json(SMTP))
    if (u.includes('/usuarios')) return Promise.resolve(json([]))
    if (u.includes('/api/instancias/')) return Promise.resolve(json(INSTANCIA))
    if (u.includes('/api/planes')) return Promise.resolve(json([]))
    if (u.includes('/api/salud')) {
      return Promise.resolve(json({
        producto: { slug: 'demolibra', nombre: 'DemoLibra' },
        features: ['instancias', 'smtp'],
        backoffice: { version: 'x', commit: 'y', arrancado: '', uptime_segundos: 61 },
        instancias: [{ slug: 'acme', nombre: 'ACME SA', container: 'c', estado: 'ok', detalle: '' }],
      }))
    }
    return Promise.resolve(json([]))
  })
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

describe('guard de rutas', () => {
  it('sin sesión manda al login', async () => {
    sinSesion()
    montar('/instancias')
    expect(await screen.findByRole('button', { name: /ingresar/i })).toBeInTheDocument()
  })

  it('con sesión muestra el inventario', async () => {
    conSesion()
    montar('/instancias')
    expect(await screen.findByText('ACME SA')).toBeInTheDocument()
    expect(screen.getByText('superadmin')).toBeInTheDocument()
  })

  it('una ruta desconocida cae en instancias', async () => {
    conSesion()
    montar('/cualquier-cosa')
    expect(await screen.findByText('ACME SA')).toBeInTheDocument()
  })
})

describe('pantalla de una instancia', () => {
  it('pide el SMTP y los usuarios DE ESA instancia', async () => {
    conSesion()
    montar('/instancias/acme')

    await waitFor(() => {
      const urls = fetchMock.mock.calls.map((c) => String(c[0]))
      expect(urls).toContain('/api/instancias/acme/smtp')
      expect(urls).toContain('/api/instancias/acme/usuarios')
    })
  })

  it('nunca pide un endpoint global, sin instancia', async () => {
    conSesion()
    montar('/instancias/acme')

    await waitFor(() => {
      expect(fetchMock.mock.calls.length).toBeGreaterThan(2)
    })
    const urls = fetchMock.mock.calls.map((c) => String(c[0]))
    expect(urls).not.toContain('/api/smtp')
    expect(urls).not.toContain('/api/usuarios')
  })

  it('muestra el nombre de la instancia arriba de todo', async () => {
    conSesion()
    montar('/instancias/acme')
    expect(await screen.findByText('ACME SA')).toBeInTheDocument()
  })
})

describe('salud', () => {
  it('lista el estado de cada instancia', async () => {
    conSesion()
    montar('/salud')
    expect(await screen.findByText('DemoLibra')).toBeInTheDocument()
    expect(await screen.findByText('ok')).toBeInTheDocument()
  })
})
