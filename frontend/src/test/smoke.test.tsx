// Humo del backoffice: que la app monte, que el guard de rutas haga lo que
// dice, y que las pantallas por instancia le peguen a la URL de ESA instancia.
//
// El Login, la tabla, `ConfiguracionSmtp` y `Usuarios` vienen de libra-ui, que
// tiene sus propios 68 tests. Acá se prueba el cableado de este repo, y sobre
// todo lo único que no puede probar libra-ui: que el `basePath` que se le pasa
// lleve el slug correcto. Es la diferencia entre configurarle el correo al
// cliente correcto y al equivocado.
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
    status,
    headers: { 'content-type': 'application/json' },
  })
}

const INSTANCIA = {
  slug: 'acme', nombre: 'ACME SA', container: 'producto-acme',
  domain: 'acme.test', port: 8081, plan: 'pro', estado: 'running',
  iniciado: '', modulos_activos: null,
  servicio_estado: 'activo', servicio_mensaje: '',
}

const SMTP = {
  origen: 'entorno', host: '', port: 587, user: '', from_email: '', from_name: '',
  password_definida: false, password_indescifrable: false, configurado: false,
}

/** Lo que devuelve el alta. `admin_password` es lo que la hace distinta de una
 *  `Instancia`: el motor la generó y esta respuesta es la única vez que sale. */
const CREADA = {
  slug: 'nueva', nombre: 'Nueva SA', domain: '', port: 8090,
  container: 'producto-nueva', admin_user: 'admin',
  admin_password: 'la-generada-por-el-motor', plan: 'basico', proxy_ok: null,
}

/** Sin sesión: `/api/me` responde 401, como con la cookie vencida. */
function sinSesion() {
  fetchMock.mockImplementation(() => Promise.resolve(json({ detail: 'No autenticado' }, 401)))
}

type Init = { method?: string } | undefined

/** Respuestas por defecto, con `rutas` para pisar las que interesen al test. */
function conSesion(rutas: Record<string, (init: Init) => Promise<Response>> = {}) {
  fetchMock.mockImplementation((url: string, init: Init) => {
    const u = String(url)
    const metodo = init?.method ?? 'GET'
    const propia = rutas[`${metodo} ${u}`] ?? rutas[u]
    if (propia) return propia(init)

    if (u.includes('/api/me')) return Promise.resolve(json({ username: 'superadmin' }))
    if (u.endsWith('/api/instancias')) {
      // La misma URL es el inventario en GET y el alta en POST.
      if (metodo === 'POST') return Promise.resolve(json(CREADA, 201))
      return Promise.resolve(json({ instancias: [INSTANCIA] }))
    }
    if (u.includes('/smtp')) return Promise.resolve(json(SMTP))
    if (u.includes('/usuarios')) return Promise.resolve(json([]))
    if (u.endsWith('/baja')) return Promise.resolve(json({ slug: 'acme', backup: null, npm: null }))
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

/** Un click que no se pelea con el `pointer-events: none` que Radix le pone al
 *  body mientras hay un diálogo modal abierto. */
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

/** Las secciones de la instancia son pestañas y **sólo se monta la activa**, así
 *  que casi todo test de esta pantalla arranca por acá. Se busca dentro del nav
 *  a propósito: «Usuarios» también es el título de la tarjeta que la pestaña
 *  abre, y `getByRole('button')` a secas terminaría matcheando lo que sea que
 *  libra-ui ponga adentro. */
async function irAPestana(u: ReturnType<typeof usuario>, label: RegExp) {
  const nav = await screen.findByRole('navigation', { name: /secciones de la instancia/i })
  await u.click(within(nav).getByRole('button', { name: label }))
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
    const u = usuario()
    montar('/instancias/acme')

    await irAPestana(u, /^correo$/i)
    await waitFor(() => {
      expect(fetchMock.mock.calls.map((c) => String(c[0]))).toContain('/api/instancias/acme/smtp')
    })

    await irAPestana(u, /^usuarios$/i)
    await waitFor(() => {
      expect(fetchMock.mock.calls.map((c) => String(c[0]))).toContain('/api/instancias/acme/usuarios')
    })
  })

  it('nunca pide un endpoint global, sin instancia', async () => {
    conSesion()
    const u = usuario()
    montar('/instancias/acme')

    // Hay que abrir las dos pestañas: si no, el test pasaría sin que el SMTP y
    // los usuarios se hubieran pedido nunca, que es la forma más barata de que
    // un `not.toContain` diga que sí sin haber probado nada.
    await irAPestana(u, /^correo$/i)
    await irAPestana(u, /^usuarios$/i)

    const urls = await waitFor(() => {
      const vistas = fetchMock.mock.calls.map((c) => String(c[0]))
      expect(vistas).toContain('/api/instancias/acme/smtp')
      expect(vistas).toContain('/api/instancias/acme/usuarios')
      return vistas
    })
    expect(urls).not.toContain('/api/smtp')
    expect(urls).not.toContain('/api/usuarios')
  })

  it('muestra el nombre de la instancia arriba de todo', async () => {
    conSesion()
    montar('/instancias/acme')
    expect(await screen.findByText('ACME SA')).toBeInTheDocument()
  })
})

// ── Las pestañas ────────────────────────────────────────────────────────────
//
// Los cuatro bloques estaban apilados. Lo que se prueba acá es lo que cambia
// con el conmutador: que arranque en General, que la pestaña viaje en la URL
// (para poder mandar el link de una sección por mensaje) y que la ficha de la
// instancia se siga viendo en todas.

describe('pestañas de la instancia', () => {
  it('arranca en General y no monta las otras secciones', async () => {
    conSesion()
    montar('/instancias/acme')

    expect(await screen.findByRole('button', { name: /^editar$/i })).toBeInTheDocument()
    expect(screen.queryByRole('combobox', { name: /^estado$/i })).not.toBeInTheDocument()
    const urls = fetchMock.mock.calls.map((c) => String(c[0]))
    expect(urls).not.toContain('/api/instancias/acme/smtp')
  })

  it('la sección pedida por la URL es la que abre', async () => {
    conSesion()
    montar('/instancias/acme?seccion=servicio')

    expect(await screen.findByRole('combobox', { name: /^estado$/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^editar$/i })).not.toBeInTheDocument()
  })

  it('una sección que no existe cae en General en vez de dejar la pantalla vacía', async () => {
    conSesion()
    montar('/instancias/acme?seccion=la-que-se-renombro')

    expect(await screen.findByRole('button', { name: /^editar$/i })).toBeInTheDocument()
  })

  it('la ficha de la instancia se ve en todas las pestañas', async () => {
    // El motivo de que la ficha quede fuera del conmutador: configurar el
    // correo sin el nombre del cliente a la vista es configurárselo al
    // equivocado.
    conSesion()
    const u = usuario()
    montar('/instancias/acme')

    for (const pestana of [/^servicio$/i, /^correo$/i, /^usuarios$/i]) {
      await irAPestana(u, pestana)
      expect(screen.getByText('ACME SA')).toBeInTheDocument()
    }
  })
})

// ── Corte de servicio ───────────────────────────────────────────────────────
//
// Vino de la pantalla de Configuración de Contalibra y Restolibra, donde el
// admin del cliente la tenía a mano: un cliente pausado se despausaba solo. Lo
// que se prueba acá es que el botón termine en la request correcta, con el
// mensaje, y que el estado que se muestra salga de la respuesta.

/** Una instancia suspendida, para las pantallas que tienen que distinguirla. */
const SUSPENDIDA = {
  ...INSTANCIA, servicio_estado: 'suspendido', servicio_mensaje: 'Factura de agosto impaga',
}

describe('corte de servicio', () => {
  it('suspende con el mensaje que se escribió', async () => {
    conSesion({
      'POST /api/instancias/acme/estado': () => Promise.resolve(json(SUSPENDIDA)),
    })
    const u = usuario()
    montar('/instancias/acme?seccion=servicio')

    await u.click(await screen.findByRole('combobox', { name: /^estado$/i }))
    await u.click(await screen.findByRole('option', { name: /suspendido/i }))
    await u.type(screen.getByLabelText(/mensaje para el cliente/i), 'Factura de agosto impaga')
    await u.click(screen.getByRole('button', { name: /^aplicar$/i }))

    await waitFor(() => {
      const post = fetchMock.mock.calls.find((c) => String(c[0]).endsWith('/acme/estado'))
      expect(post).toBeDefined()
      expect(cuerpoDe(post!)).toEqual({ accion: 'suspender', mensaje: 'Factura de agosto impaga' })
    })
  })

  it('activar no arrastra el mensaje del corte anterior', async () => {
    // El motor lo limpia, pero el formulario tiene el texto cargado: si lo
    // mandara, cualquier cambio del lado del motor lo re-guardaría.
    conSesion({
      'GET /api/instancias/acme': () => Promise.resolve(json(SUSPENDIDA)),
      'POST /api/instancias/acme/estado': () => Promise.resolve(json(INSTANCIA)),
    })
    const u = usuario()
    montar('/instancias/acme?seccion=servicio')

    expect(await screen.findByDisplayValue('Factura de agosto impaga')).toBeInTheDocument()
    await u.click(screen.getByRole('combobox', { name: /^estado$/i }))
    await u.click(await screen.findByRole('option', { name: /activo/i }))
    await u.click(screen.getByRole('button', { name: /^aplicar$/i }))

    await waitFor(() => {
      const post = fetchMock.mock.calls.find((c) => String(c[0]).endsWith('/acme/estado'))
      expect(post).toBeDefined()
      expect(cuerpoDe(post!)).toEqual({ accion: 'activar', mensaje: '' })
    })
  })

  it('el mensaje no se pide cuando el estado es Activo', async () => {
    conSesion()
    montar('/instancias/acme?seccion=servicio')
    await screen.findByRole('combobox', { name: /^estado$/i })
    expect(screen.queryByLabelText(/mensaje para el cliente/i)).not.toBeInTheDocument()
  })

  it('un contenedor running suspendido no se muestra como si estuviera bien', async () => {
    // El caso que motiva tener los dos ejes: `estado` sigue diciendo `running`
    // porque el contenedor efectivamente corre — devolviendo 503 a todo.
    conSesion({ 'GET /api/instancias': () => Promise.resolve(json({ instancias: [SUSPENDIDA] })) })
    montar('/instancias')

    expect(await screen.findByText('ACME SA')).toBeInTheDocument()
    expect(screen.getByText('running')).toBeInTheDocument()
    expect(screen.getByText('suspendido')).toBeInTheDocument()
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

// ── Alta ────────────────────────────────────────────────────────────────────
//
// Estas tres pantallas existían en el backoffice Jinja2 y no se habían portado:
// el backend las tenía, el SPA no las llamaba. Lo que se prueba acá es
// justamente eso, que el botón termine en la request.

async function abrirAlta() {
  const u = usuario()
  montar('/instancias')
  await u.click(await screen.findByRole('button', { name: /nueva instancia/i }))
  return u
}

describe('alta de una instancia', () => {
  it('manda el alta con lo poco que se completó, sin inventar el resto', async () => {
    conSesion()
    const u = await abrirAlta()

    await u.type(screen.getByLabelText(/nombre del cliente/i), 'Nueva SA')
    await u.click(screen.getByRole('button', { name: /crear instancia/i }))

    await waitFor(() => {
      const alta = fetchMock.mock.calls.find(
        (c) => String(c[0]).endsWith('/api/instancias') && (c[1] as Init)?.method === 'POST',
      )
      expect(alta).toBeDefined()
      const cuerpo = cuerpoDe(alta!)
      expect(cuerpo.nombre).toBe('Nueva SA')
      // Vacíos NO se mandan: el motor deriva el slug del nombre y toma el
      // próximo puerto libre. Mandar "" o 0 le pisaría esos defaults.
      expect(cuerpo).not.toHaveProperty('slug')
      expect(cuerpo).not.toHaveProperty('port')
      expect(cuerpo).not.toHaveProperty('admin_password')
    })
  })

  it('muestra la contraseña generada, que no vuelve por ningún otro lado', async () => {
    conSesion()
    const u = await abrirAlta()

    await u.type(screen.getByLabelText(/nombre del cliente/i), 'Nueva SA')
    await u.click(screen.getByRole('button', { name: /crear instancia/i }))

    expect(await screen.findByText('la-generada-por-el-motor')).toBeInTheDocument()
  })

  it('avisa que no se reintente si la instancia apareció pese al error', async () => {
    // El caso real: `docker compose up` + la espera de la base + el certificado
    // pasan del minuto, el proxy corta la respuesta, y el alta termina igual.
    // Reintentar a ciegas crearía un segundo cliente.
    let altas = 0
    conSesion({
      'POST /api/instancias': () => {
        altas += 1
        return Promise.resolve(json({ detail: 'Gateway Timeout' }, 504))
      },
      'GET /api/instancias': () =>
        Promise.resolve(json({
          instancias: altas ? [INSTANCIA, { ...INSTANCIA, slug: 'nueva' }] : [INSTANCIA],
        })),
    })
    const u = await abrirAlta()

    await u.type(screen.getByLabelText(/nombre del cliente/i), 'Nueva SA')
    await u.click(screen.getByRole('button', { name: /crear instancia/i }))

    expect(await screen.findByText(/no reintentes todavía/i)).toBeInTheDocument()
  })

  it('un 422 es un rechazo del motor: no se sale a buscar instancias huérfanas', async () => {
    conSesion({
      'POST /api/instancias': () =>
        Promise.resolve(json({ detail: 'Ya existe un cliente con slug «acme».' }, 422)),
    })
    const u = await abrirAlta()

    await u.type(screen.getByLabelText(/nombre del cliente/i), 'ACME')
    await u.click(screen.getByRole('button', { name: /crear instancia/i }))

    expect(await screen.findByText(/ya existe un cliente/i)).toBeInTheDocument()
    expect(screen.queryByText(/no reintentes todavía/i)).not.toBeInTheDocument()
  })
})

// ── Editar y baja ───────────────────────────────────────────────────────────

describe('editar una instancia', () => {
  it('guarda nombre y dominio con un PUT', async () => {
    conSesion()
    const u = usuario()
    montar('/instancias/acme')

    await u.click(await screen.findByRole('button', { name: /^editar$/i }))
    const nombre = screen.getByLabelText(/^nombre$/i)
    await u.clear(nombre)
    await u.type(nombre, 'ACME SRL')
    await u.click(screen.getByRole('button', { name: /guardar/i }))

    await waitFor(() => {
      const put = fetchMock.mock.calls.find((c) => (c[1] as Init)?.method === 'PUT')
      expect(put).toBeDefined()
      expect(String(put![0])).toBe('/api/instancias/acme')
      expect(cuerpoDe(put!)).toEqual({ nombre: 'ACME SRL', domain: 'acme.test' })
    })
  })
})

describe('baja de una instancia', () => {
  it('no deja confirmar hasta que el slug escrito coincide', async () => {
    conSesion()
    const u = usuario()
    montar('/instancias/acme')

    await u.click(await screen.findByRole('button', { name: /dar de baja/i }))
    const dialogo = screen.getByRole('dialog')
    const confirmar = within(dialogo).getByRole('button', { name: /dar de baja/i })
    expect(confirmar).toBeDisabled()

    await u.type(within(dialogo).getByLabelText(/para confirmar/i), 'acmee')
    expect(confirmar).toBeDisabled()

    await u.clear(within(dialogo).getByLabelText(/para confirmar/i))
    await u.type(within(dialogo).getByLabelText(/para confirmar/i), 'acme')
    expect(confirmar).toBeEnabled()
  })

  it('pega en /baja con el slug repetido y el backup pedido', async () => {
    conSesion()
    const u = usuario()
    montar('/instancias/acme')

    await u.click(await screen.findByRole('button', { name: /dar de baja/i }))
    const dialogo = screen.getByRole('dialog')
    await u.type(within(dialogo).getByLabelText(/para confirmar/i), 'acme')
    await u.click(within(dialogo).getByRole('button', { name: /dar de baja/i }))

    await waitFor(() => {
      const baja = fetchMock.mock.calls.find((c) => String(c[0]).endsWith('/baja'))
      expect(baja).toBeDefined()
      // POST, no DELETE: el api-client compartido manda DELETE sin cuerpo y la
      // confirmación viaja en el cuerpo.
      expect((baja![1] as Init)?.method).toBe('POST')
      expect(String(baja![0])).toBe('/api/instancias/acme/baja')
      expect(cuerpoDe(baja!)).toEqual({ confirmar_slug: 'acme', hacer_backup: true })
    })
  })

  it('vuelve al inventario mostrando dónde quedó el backup', async () => {
    conSesion({
      'POST /api/instancias/acme/baja': () =>
        Promise.resolve(json({
          slug: 'acme', backup: '/root/producto/clientes/acme_backup_20260802.tar.gz', npm: true,
        })),
    })
    const u = usuario()
    montar('/instancias/acme')

    await u.click(await screen.findByRole('button', { name: /dar de baja/i }))
    const dialogo = screen.getByRole('dialog')
    await u.type(within(dialogo).getByLabelText(/para confirmar/i), 'acme')
    await u.click(within(dialogo).getByRole('button', { name: /dar de baja/i }))

    expect(
      await screen.findByText(/acme_backup_20260802\.tar\.gz/),
    ).toBeInTheDocument()
  })
})
