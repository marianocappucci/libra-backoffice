// La pestaña «Marca»: el orden que evita dejar a los usuarios de un cliente sin poder entrar (primero los términos, después la marca), el logo (un
// archivo), la confirmación de lo que no se deshace, y que «Apariencia» muestre sin alarma a las instancias de marca blanca.
//
// La "instancia" es un doble CON ESTADO que sigue el contrato del backend (`routers/marca.py`): así lo que se prueba es lo que la pantalla muestra
// después de cada acción, no que se haya llamado a una URL. El contrato de verdad con el motor lo fijan los tests de Python con el router real.
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
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
}

const INSTANCIA = {
  slug: 'acme', nombre: 'ACME SA', container: 'producto-acme', domain: 'acme.test', port: 8081, plan: 'pro', estado: 'running',
  iniciado: '', modulos_activos: null, servicio_estado: 'activo', servicio_mensaje: '',
}

const MARCA_VACIA = { propia: false, nombre: '', nombre_corto: '', color: '', logo: '', terminos_propios: false }
const SIN_TERMINOS = { cargados: false, version: '', vigente_desde: '', hash: '', caracteres: 0 }
const HASH = 'a'.repeat(64)
const TERMINOS_PUESTOS = { cargados: true, version: '2026-1', vigente_desde: '01-11-2026', hash: HASH, caracteres: 1234 }

type Init = { method?: string; body?: unknown } | undefined

/** La instancia: lo que cada ruta contesta y cambia, con las mismas reglas del backend. */
function instanciaConEstado(inicial: { marca?: Partial<typeof MARCA_VACIA>; terminos?: typeof SIN_TERMINOS } = {}) {
  const estado = {
    marca: { ...MARCA_VACIA, ...inicial.marca },
    terminos: inicial.terminos ?? SIN_TERMINOS,
    llamadas: [] as { metodo: string; url: string; cuerpo?: unknown }[],
  }
  const sincronizar = () => { estado.marca.terminos_propios = estado.terminos.cargados }
  sincronizar()

  const rutas: Record<string, (init: Init, url: string) => Response> = {
    'GET /api/instancias/acme/marca': () => json({ marca: estado.marca, terminos: estado.terminos, producto: 'gestiolibra' }),
    'PUT /api/instancias/acme/marca': (init) => {
      const cuerpo = JSON.parse(String(init?.body))
      if (!estado.marca.propia && !estado.terminos.cargados && !cuerpo.sin_terminos) {
        return json({ detail: { code: 'terminos_primero', mensaje: 'Cargá primero los Términos y Condiciones de esta instancia.' } }, 409)
      }
      estado.marca = { ...estado.marca, nombre: cuerpo.nombre, nombre_corto: cuerpo.nombre_corto, color: cuerpo.color, propia: true }
      sincronizar()
      return json(estado.marca)
    },
    'PUT /api/instancias/acme/marca/terminos': (init) => {
      const cuerpo = JSON.parse(String(init?.body))
      if (cuerpo.version === 'repetida') return json({ detail: 'La versión repetida ya se publicó con otro texto. Una versión es un texto: usá otro número de versión.' }, 409)
      estado.terminos = { cargados: true, version: cuerpo.version, vigente_desde: cuerpo.vigente_desde, hash: HASH, caracteres: cuerpo.texto.length }
      sincronizar()
      return json(estado.terminos)
    },
    'POST /api/instancias/acme/marca/logo': () => {
      estado.marca = { ...estado.marca, propia: true, logo: '/api/marca/logo?v=0123456789ab' }
      return json(estado.marca)
    },
    'DELETE /api/instancias/acme/marca/logo': () => {
      estado.marca = { ...estado.marca, logo: '' }
      return json(estado.marca)
    },
    'DELETE /api/instancias/acme/marca': () => {
      estado.marca = { ...MARCA_VACIA }
      estado.terminos = SIN_TERMINOS
      return json(estado.marca)
    },
  }
  return { estado, rutas }
}

function conSesion(
  instancia: ReturnType<typeof instanciaConEstado> | null,
  { features = ['instancias', 'marca', 'apariencia'], extra = {} as Record<string, (init: Init) => Response> } = {},
) {
  fetchMock.mockImplementation((url: string, init: Init) => {
    const u = String(url)
    const metodo = init?.method ?? 'GET'
    instancia?.estado.llamadas.push({ metodo, url: u, cuerpo: init?.body })
    const sinQuery = u.split('?')[0]

    if (instancia) {
      if (metodo === 'DELETE' && sinQuery === '/api/instancias/acme/marca/terminos') {
        const e = instancia.estado
        if (!u.includes('confirmar=true') && e.marca.propia) {
          return Promise.resolve(json({ detail: { code: 'quedaria_frenada', mensaje: 'Esta instancia tiene marca propia: sin sus Términos queda frenada.' } }, 409))
        }
        e.terminos = SIN_TERMINOS
        e.marca.terminos_propios = false
        return Promise.resolve(json(e.terminos))
      }
      const propia = instancia.rutas[`${metodo} ${sinQuery}`]
      if (propia) return Promise.resolve(propia(init, u))
    }
    const extraRuta = extra[`${metodo} ${sinQuery}`] ?? extra[sinQuery]
    if (extraRuta) return Promise.resolve(extraRuta(init))

    if (sinQuery === '/api/me') return Promise.resolve(json({ username: 'superadmin', features }))
    if (sinQuery.startsWith('/api/instancias/acme/')) return Promise.resolve(json({}))
    if (sinQuery === '/api/instancias/acme') return Promise.resolve(json(INSTANCIA))
    if (sinQuery === '/api/planes') return Promise.resolve(json([]))
    return Promise.resolve(json([]))
  })
}

const usuario = () => userEvent.setup({ pointerEventsCheck: 0 })

function montar(ruta: string) {
  return render(
    <MemoryRouter initialEntries={[ruta]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
}

async function irAMarca(u: ReturnType<typeof usuario>) {
  const nav = await screen.findByRole('navigation', { name: /secciones de la instancia/i })
  await u.click(within(nav).getByRole('button', { name: /^marca$/i }))
}

function llamadas(i: ReturnType<typeof instanciaConEstado>, metodo: string, ruta: string) {
  return i.estado.llamadas.filter((c) => c.metodo === metodo && c.url.split('?')[0] === ruta)
}

describe('la pestaña Marca', () => {
  it('existe sólo si el producto tiene la feature', async () => {
    conSesion(instanciaConEstado(), { features: ['instancias', 'smtp'] })
    montar('/instancias/acme')
    const nav = await screen.findByRole('navigation', { name: /secciones de la instancia/i })
    expect(within(nav).queryByRole('button', { name: /^marca$/i })).not.toBeInTheDocument()
  })

  it('con la feature aparece', async () => {
    conSesion(instanciaConEstado())
    montar('/instancias/acme')
    const nav = await screen.findByRole('navigation', { name: /secciones de la instancia/i })
    expect(within(nav).getByRole('button', { name: /^marca$/i })).toBeInTheDocument()
  })

  it('una instancia sin marca lo dice, y no alarma', async () => {
    conSesion(instanciaConEstado())
    montar('/instancias/acme')
    await irAMarca(usuario())

    expect(await screen.findByText('Marca del producto')).toBeInTheDocument()
    expect(screen.getByText(/términos propios: sin cargar/i)).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('lee la marca de ESA instancia', async () => {
    const i = instanciaConEstado()
    conSesion(i)
    montar('/instancias/acme')
    await irAMarca(usuario())
    await screen.findByText('Marca del producto')
    expect(llamadas(i, 'GET', '/api/instancias/acme/marca')).toHaveLength(1)
  })

  it('una instancia vieja dice que hay que actualizarla y no dibuja formularios', async () => {
    conSesion(null, {
      extra: {
        'GET /api/instancias/acme/marca': () => json({ detail: 'La instancia todavía no tiene la marca (libracore anterior a v1.206.0): hay que actualizarla.' }, 409),
      },
    })
    montar('/instancias/acme')
    await irAMarca(usuario())

    expect(await screen.findByText('Esta instancia todavía no tiene la marca')).toBeInTheDocument()
    expect(screen.getByText(/hay que actualizarla/i)).toBeInTheDocument()
    expect(screen.queryByLabelText(/^nombre$/i)).not.toBeInTheDocument()
  })
})

describe('1. los términos primero', () => {
  it('el botón de guardar espera a los tres campos', async () => {
    conSesion(instanciaConEstado())
    montar('/instancias/acme')
    const u = usuario()
    await irAMarca(u)
    const guardar = await screen.findByRole('button', { name: /guardar términos/i })
    expect(guardar).toBeDisabled()

    await u.type(screen.getByLabelText(/^versión$/i), '2026-1')
    await u.type(screen.getByLabelText(/vigente desde/i), '01-11-2026')
    expect(guardar).toBeDisabled()
    await u.type(screen.getByLabelText(/texto \(markdown\)/i), '# Términos')
    expect(guardar).toBeEnabled()
  })

  it('guarda a la URL de ESA instancia y la pantalla muestra lo cargado, sin releer el texto', async () => {
    const i = instanciaConEstado()
    conSesion(i)
    montar('/instancias/acme')
    const u = usuario()
    await irAMarca(u)

    await u.type(await screen.findByLabelText(/^versión$/i), ' 2026-1 ')
    await u.type(screen.getByLabelText(/vigente desde/i), '01-11-2026')
    await u.type(screen.getByLabelText(/texto \(markdown\)/i), '# Términos de Gestión Sur')
    await u.click(screen.getByRole('button', { name: /guardar términos/i }))

    const cargados = await screen.findByTestId('terminos-cargados')
    expect(cargados).toHaveTextContent('2026-1')
    expect(cargados).toHaveTextContent('01-11-2026')
    expect(cargados).toHaveTextContent('aaaaaaaaaaaa…') // la huella, no el texto
    expect(screen.getByLabelText(/texto \(markdown\)/i)).toHaveValue('') // y el campo se vacía: el texto no se puede releer
    const [envio] = llamadas(i, 'PUT', '/api/instancias/acme/marca/terminos')
    expect(JSON.parse(String(envio.cuerpo))).toEqual({ version: '2026-1', vigente_desde: '01-11-2026', texto: '# Términos de Gestión Sur' })
  })

  it('el rechazo de la instancia (una versión es un texto) se ve donde se escribió', async () => {
    conSesion(instanciaConEstado())
    montar('/instancias/acme')
    const u = usuario()
    await irAMarca(u)
    await u.type(await screen.findByLabelText(/^versión$/i), 'repetida')
    await u.type(screen.getByLabelText(/vigente desde/i), '01-11-2026')
    await u.type(screen.getByLabelText(/texto \(markdown\)/i), 'otro')
    await u.click(screen.getByRole('button', { name: /guardar términos/i }))

    expect(await screen.findByText(/usá otro número de versión/i)).toBeInTheDocument()
  })

  it('guardar la marca sin términos se rechaza y ofrece seguir sólo a sabiendas', async () => {
    const i = instanciaConEstado()
    conSesion(i)
    montar('/instancias/acme')
    const u = usuario()
    await irAMarca(u)

    await u.type(await screen.findByLabelText(/^nombre$/i), 'Gestión Sur')
    expect(screen.queryByLabelText(/guardar igual/i)).not.toBeInTheDocument()
    await u.click(screen.getByRole('button', { name: /guardar marca/i }))

    expect(await screen.findByText(/cargá primero los términos/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/guardar igual/i)).not.toBeChecked()
    expect(i.estado.marca.propia).toBe(false) // no se guardó nada
    const [primero] = llamadas(i, 'PUT', '/api/instancias/acme/marca')
    expect(JSON.parse(String(primero.cuerpo)).sin_terminos).toBe(false)
  })

  it('tildar «guardar igual» manda el permiso, y la pantalla avisa que los usuarios no pueden entrar', async () => {
    const i = instanciaConEstado()
    conSesion(i)
    montar('/instancias/acme')
    const u = usuario()
    await irAMarca(u)
    await u.type(await screen.findByLabelText(/^nombre$/i), 'Gestión Sur')
    await u.click(screen.getByRole('button', { name: /guardar marca/i }))
    await u.click(await screen.findByLabelText(/guardar igual/i))
    await u.click(screen.getByRole('button', { name: /guardar marca/i }))

    const alerta = await screen.findByRole('alert')
    expect(alerta).toHaveTextContent(/no pueden entrar/i)
    expect(screen.getByText('Marca propia')).toBeInTheDocument()
    const enviadas = llamadas(i, 'PUT', '/api/instancias/acme/marca')
    expect(JSON.parse(String(enviadas[1].cuerpo)).sin_terminos).toBe(true)
  })

  it('con los términos cargados la marca se guarda sin permisos especiales y no hay alerta', async () => {
    const i = instanciaConEstado({ terminos: TERMINOS_PUESTOS })
    conSesion(i)
    montar('/instancias/acme')
    const u = usuario()
    await irAMarca(u)

    await u.type(await screen.findByLabelText(/^nombre$/i), 'Gestión Sur')
    await u.type(screen.getByLabelText(/nombre corto/i), 'GSur')
    await u.type(screen.getByLabelText(/color de la marca/i), '#336699')
    await u.click(screen.getByRole('button', { name: /guardar marca/i }))

    expect(await screen.findByText('Marca guardada.')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    const [envio] = llamadas(i, 'PUT', '/api/instancias/acme/marca')
    expect(JSON.parse(String(envio.cuerpo))).toEqual({ nombre: 'Gestión Sur', nombre_corto: 'GSur', color: '#336699', sin_terminos: false })
  })

  it('un color que no es #rrggbb no se puede guardar', async () => {
    conSesion(instanciaConEstado({ terminos: TERMINOS_PUESTOS }))
    montar('/instancias/acme')
    const u = usuario()
    await irAMarca(u)
    await u.type(await screen.findByLabelText(/^nombre$/i), 'Gestión Sur')
    await u.type(screen.getByLabelText(/color de la marca/i), 'rojo')

    expect(screen.getByText(/se espera #rrggbb/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /guardar marca/i })).toBeDisabled()
  })

  it('una instancia que ya es propia se puede retocar sin pedir los términos', async () => {
    const i = instanciaConEstado({ marca: { propia: true, nombre: 'Gestión Sur' } })
    conSesion(i)
    montar('/instancias/acme')
    const u = usuario()
    await irAMarca(u)
    const campo = await screen.findByLabelText(/^nombre$/i)
    expect(campo).toHaveValue('Gestión Sur')
    await u.type(campo, ' SRL')
    await u.click(screen.getByRole('button', { name: /guardar marca/i }))
    expect(await screen.findByText('Marca guardada.')).toBeInTheDocument()
  })

  it('quitar los términos de una instancia con marca pide confirmar, y recién ahí los quita', async () => {
    const i = instanciaConEstado({ marca: { propia: true, nombre: 'Gestión Sur' }, terminos: TERMINOS_PUESTOS })
    conSesion(i)
    montar('/instancias/acme')
    const u = usuario()
    await irAMarca(u)
    await u.click(await screen.findByRole('button', { name: /quitar los términos/i }))

    const dialogo = await screen.findByRole('alertdialog')
    expect(dialogo).toHaveTextContent(/queda frenada/i)
    expect(i.estado.terminos.cargados).toBe(true) // todavía están
    await u.click(within(dialogo).getByRole('button', { name: /quitarlos igual/i }))

    await waitFor(() => expect(i.estado.terminos.cargados).toBe(false))
    expect(llamadas(i, 'DELETE', '/api/instancias/acme/marca/terminos').some((c) => c.url.includes('confirmar=true'))).toBe(true)
    expect(await screen.findByRole('alert')).toHaveTextContent(/no pueden entrar/i)
  })

  it('cancelar la confirmación no quita nada', async () => {
    const i = instanciaConEstado({ marca: { propia: true, nombre: 'Gestión Sur' }, terminos: TERMINOS_PUESTOS })
    conSesion(i)
    montar('/instancias/acme')
    const u = usuario()
    await irAMarca(u)
    await u.click(await screen.findByRole('button', { name: /quitar los términos/i }))
    await u.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: /cancelar/i }))

    expect(i.estado.terminos.cargados).toBe(true)
    expect(llamadas(i, 'DELETE', '/api/instancias/acme/marca/terminos').every((c) => !c.url.includes('confirmar=true'))).toBe(true)
  })
})

describe('el logo', () => {
  it('se sube como archivo a ESA instancia y aparece la vista previa', async () => {
    const i = instanciaConEstado({ terminos: TERMINOS_PUESTOS })
    conSesion(i)
    montar('/instancias/acme')
    const u = usuario()
    await irAMarca(u)

    const archivo = new File([new Uint8Array([137, 80, 78, 71])], 'logo.png', { type: 'image/png' })
    await u.upload(await screen.findByLabelText(/elegir logo/i), archivo)

    expect(await screen.findByText('Logo guardado.')).toBeInTheDocument()
    const [envio] = llamadas(i, 'POST', '/api/instancias/acme/marca/logo')
    expect(envio.cuerpo).toBeInstanceOf(FormData)
    expect((envio.cuerpo as FormData).get('logo')).toBeInstanceOf(File)
    const vista = screen.getByLabelText(/vista previa de la marca/i).querySelector('img')
    expect(vista).toHaveAttribute('src', '/api/instancias/acme/marca/logo?v=0123456789ab')
  })

  it('sin términos, el rechazo aparece junto al logo y no se sube nada', async () => {
    const i = instanciaConEstado()
    conSesion(i, {
      extra: {},
    })
    // El doble de arriba no modela el 409 del logo: se lo da la ruta específica.
    i.rutas['POST /api/instancias/acme/marca/logo'] = () =>
      json({ detail: { code: 'terminos_primero', mensaje: 'Cargá primero los Términos y Condiciones de esta instancia.' } }, 409)
    montar('/instancias/acme')
    const u = usuario()
    await irAMarca(u)
    await u.upload(await screen.findByLabelText(/elegir logo/i), new File(['x'], 'logo.png', { type: 'image/png' }))

    expect(await screen.findByText(/cargá primero los términos/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/guardar igual/i)).toBeInTheDocument()
    expect(i.estado.marca.logo).toBe('')
  })

  it('quitar el logo conserva el resto', async () => {
    const i = instanciaConEstado({ marca: { propia: true, nombre: 'Gestión Sur', logo: '/api/marca/logo?v=0123456789ab' }, terminos: TERMINOS_PUESTOS })
    conSesion(i)
    montar('/instancias/acme')
    const u = usuario()
    await irAMarca(u)
    await u.click(await screen.findByRole('button', { name: /quitar logo/i }))

    expect(await screen.findByText('Logo quitado.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /quitar logo/i })).not.toBeInTheDocument()
    expect(screen.getByLabelText(/^nombre$/i)).toHaveValue('Gestión Sur')
  })

  it('la vista previa sin logo dibuja la inicial del nombre', async () => {
    conSesion(instanciaConEstado({ marca: { propia: true, nombre: 'ñandú' }, terminos: TERMINOS_PUESTOS }))
    montar('/instancias/acme')
    await irAMarca(usuario())
    await screen.findByLabelText(/^nombre$/i)
    expect(within(screen.getByLabelText(/vista previa de la marca/i)).getByText('Ñ')).toBeInTheDocument()
  })
})

describe('volver a la marca del producto', () => {
  it('no se ofrece si la instancia no tiene nada propio', async () => {
    conSesion(instanciaConEstado())
    montar('/instancias/acme')
    await irAMarca(usuario())
    await screen.findByText('Marca del producto')
    expect(screen.queryByRole('button', { name: /volver a la marca del producto/i })).not.toBeInTheDocument()
  })

  it('pide confirmación, avisa que se llevan los términos, y recién ahí lo hace', async () => {
    const i = instanciaConEstado({ marca: { propia: true, nombre: 'Gestión Sur' }, terminos: TERMINOS_PUESTOS })
    conSesion(i)
    montar('/instancias/acme')
    const u = usuario()
    await irAMarca(u)
    await u.click(await screen.findByRole('button', { name: /^volver a la marca del producto$/i }))

    const dialogo = await screen.findByRole('alertdialog')
    expect(dialogo).toHaveTextContent(/términos propios/i)
    expect(llamadas(i, 'DELETE', '/api/instancias/acme/marca')).toHaveLength(0)
    await u.click(within(dialogo).getByRole('button', { name: /volver a la marca del producto/i }))

    expect(await screen.findByText(/vuelve a la marca de su producto/i)).toBeInTheDocument()
    expect(i.estado.marca.propia).toBe(false)
    expect(i.estado.terminos.cargados).toBe(false)
  })
})

describe('«Apariencia» con una instancia de marca blanca', () => {
  it('la muestra como «Marca propia», sin alarma', async () => {
    conSesion(null, {
      extra: {
        '/api/apariencia': () => json({ tema: {}, producto: 'gestiolibra' }),
        '/api/apariencia/estado': () => json({
          tema: {},
          instancias: [
            { slug: 'acme', nombre: 'ACME SA', estado: 'marca_propia', detalle: 'Tiene marca propia: no se le aplica el tema de la suite.' },
            { slug: 'beta', nombre: 'Beta SRL', estado: 'al_dia', detalle: '' },
          ],
        }),
      },
    })
    montar('/apariencia')

    const insignia = await screen.findByText('Marca propia')
    expect(insignia).toBeInTheDocument()
    expect(screen.getByText(/no se le aplica el tema de la suite/i)).toBeInTheDocument()
    expect(screen.getByText('Al día')).toBeInTheDocument()
  })
})
