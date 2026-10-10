// Las sucursales contratadas y el abono (ADR-041 de libracore): la línea «Plan único $39.900 + N sucursales adicionales × $19.950 = $X», «Activas A
// de C contratadas», el campo «Sucursales contratadas» con Guardar, y el mismo campo en el alta con default 1. Sólo para los planes que declaran
// `adicional`: los demás productos no ven nada nuevo (ni una request).
import { configure, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { AltaInstancia } from '../components/AltaInstancia'
import { Instancia } from '../pages/Instancia'

// La primera pantalla de la corrida paga el import de libra-ui: un segundo no alcanza en frío (pasa sola, falla en la suite).
configure({ asyncUtilTimeout: 5000 })

const INSTANCIA = {
  slug: 'acme', nombre: 'ACME SA', container: 'producto-acme',
  domain: 'acme.test', port: 8081, plan: 'unico', estado: 'running',
  iniciado: '', modulos_activos: null, servicio_estado: 'activo', servicio_mensaje: '',
}

const ADICIONAL = { unidad: 'sucursal', incluidas: 1, precio: 19950 }
const PLAN_UNICO = { key: 'unico', label: 'Plan único', precio: 39900, modulos: [], adicional: ADICIONAL }
const PLAN_SIN_ADICIONAL = { key: 'basico', label: 'Básico', precio: 1000, modulos: [], adicional: null }

/** Lo que contesta `GET /api/instancias/acme/abono` para `contratadas` y `activas`, con el cálculo de `calcular_abono`. */
function abono(contratadas: number | null, activas = 1) {
  const adicionales = contratadas === null ? 0 : Math.max(0, contratadas - 1)
  return {
    slug: 'acme', plan: 'unico', plan_label: 'Plan único', aplica: true, estado: 'ok', detalle: '',
    unidad: 'sucursal', incluidas: 1, precio_base: 39900, precio_adicional: 19950,
    contratadas, activas,
    abono: {
      contratadas, incluidas: 1, base: 39900, adicionales, precio_adicional: 19950,
      extra: adicionales * 19950, total: 39900 + adicionales * 19950,
    },
  }
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
}

let fetchMock: ReturnType<typeof vi.fn>

type Init = { method?: string; body?: string } | undefined

/** `respuestaAbono` contesta el GET y el PUT de `/abono` y `/sucursales`. */
function montarInstancia(planes: unknown[], respuestaAbono: (metodo: string, init: Init) => Response) {
  fetchMock = vi.fn((url: string, init?: Init) => {
    const u = String(url)
    const metodo = init?.method ?? 'GET'
    if (u.includes('/abono') || u.includes('/sucursales')) return Promise.resolve(respuestaAbono(metodo, init))
    if (u.includes('/addons')) return Promise.resolve(json({}))
    if (u.includes('/api/planes')) return Promise.resolve(json(planes))
    if (u.includes('/api/instancias/acme')) return Promise.resolve(json(INSTANCIA))
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

const urlsPedidas = () => fetchMock.mock.calls.map((c) => String(c[0]))

beforeEach(() => {
  vi.unstubAllGlobals()
})

describe('sucursales contratadas en la pantalla de una instancia', () => {
  it('muestra la línea del abono y las activas contra las contratadas', async () => {
    montarInstancia([PLAN_UNICO], () => json(abono(2, 1)))

    expect(
      await screen.findByText('Plan único $39.900 + 1 sucursal adicional × $19.950 = $59.850 (IVA incluido)'),
    ).toBeInTheDocument()
    expect(screen.getByText(/Activas 1 de 2 contratadas/)).toBeInTheDocument()
    expect(screen.getByLabelText('Sucursales contratadas')).toHaveValue(2)
  })

  it('con 3 contratadas dice «2 sucursales adicionales» en plural y suma 79.800', async () => {
    montarInstancia([PLAN_UNICO], () => json(abono(3, 2)))
    expect(
      await screen.findByText('Plan único $39.900 + 2 sucursales adicionales × $19.950 = $79.800 (IVA incluido)'),
    ).toBeInTheDocument()
  })

  it('sin dato cargado dice «Sin cargar», que no hay límite, y no inventa un 1', async () => {
    montarInstancia([PLAN_UNICO], () => json(abono(null, 2)))

    expect(await screen.findByText(/Activas 2 de Sin cargar contratadas \(sin límite\)/)).toBeInTheDocument()
    expect(screen.getByLabelText('Sucursales contratadas')).toHaveValue(null)
    expect(screen.getByRole('button', { name: 'Guardar' })).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Quitar límite' })).not.toBeInTheDocument()
  })

  it('Guardar manda las contratadas a la instancia y refresca la línea con lo que devuelve el backend', async () => {
    const usuario = userEvent.setup()
    montarInstancia([PLAN_UNICO], (metodo, init) =>
      metodo === 'PUT' ? json(abono(JSON.parse(String(init!.body)).contratadas, 1)) : json(abono(null, 1)),
    )

    const campo = await screen.findByLabelText('Sucursales contratadas')
    await usuario.type(campo, '3')
    await usuario.click(screen.getByRole('button', { name: 'Guardar' }))

    await waitFor(() => {
      const put = fetchMock.mock.calls.find((c) => String(c[0]).endsWith('/api/instancias/acme/sucursales'))
      expect(put).toBeDefined()
      expect((put![1] as Init)?.method).toBe('PUT')
      expect(JSON.parse(String((put![1] as Init)?.body))).toEqual({ contratadas: 3 })
    })
    expect(
      await screen.findByText('Plan único $39.900 + 2 sucursales adicionales × $19.950 = $79.800 (IVA incluido)'),
    ).toBeInTheDocument()
    expect(screen.getByText('Sucursales contratadas guardadas.')).toBeInTheDocument()
  })

  it('no deja guardar un 0 ni lo que ya está guardado', async () => {
    const usuario = userEvent.setup()
    montarInstancia([PLAN_UNICO], () => json(abono(2, 1)))
    const campo = await screen.findByLabelText('Sucursales contratadas')
    const guardar = screen.getByRole('button', { name: 'Guardar' })

    expect(guardar).toBeDisabled() // el mismo número que ya tiene
    await usuario.clear(campo)
    await usuario.type(campo, '0')
    expect(guardar).toBeDisabled()
    await usuario.clear(campo)
    expect(guardar).toBeDisabled() // vacío no es «quitar»: para eso está su botón
    await usuario.type(campo, '4')
    expect(guardar).toBeEnabled()
  })

  it('«Quitar límite» manda null', async () => {
    const usuario = userEvent.setup()
    montarInstancia([PLAN_UNICO], (metodo) => (metodo === 'PUT' ? json(abono(null, 1)) : json(abono(2, 1))))

    await usuario.click(await screen.findByRole('button', { name: 'Quitar límite' }))

    await waitFor(() => {
      const put = fetchMock.mock.calls.find((c) => String(c[0]).endsWith('/api/instancias/acme/sucursales'))
      expect(JSON.parse(String((put![1] as Init)?.body))).toEqual({ contratadas: null })
    })
    expect(await screen.findByText(/Activas 1 de Sin cargar contratadas/)).toBeInTheDocument()
  })

  it('avisa si hay más activas que contratadas', async () => {
    montarInstancia([PLAN_UNICO], () => json(abono(1, 3)))
    expect(await screen.findByText(/más sucursales activas que las contratadas/)).toBeInTheDocument()
  })

  it('si el backend rechaza el guardado, muestra el motivo y deja el campo', async () => {
    const usuario = userEvent.setup()
    montarInstancia([PLAN_UNICO], (metodo) =>
      metodo === 'PUT' ? json({ detail: 'La instancia no responde.' }, 502) : json(abono(null, 1)),
    )
    const campo = await screen.findByLabelText('Sucursales contratadas')
    await usuario.type(campo, '2')
    await usuario.click(screen.getByRole('button', { name: 'Guardar' }))

    expect(await screen.findByText('La instancia no responde.')).toBeInTheDocument()
    expect(campo).toHaveValue(2)
  })

  it('una instancia sin el endpoint (libracore vieja) dice que hay que actualizarla y no ofrece cargar nada', async () => {
    montarInstancia([PLAN_UNICO], () =>
      json({
        slug: 'acme', plan: 'unico', plan_label: 'Plan único', aplica: true, estado: 'sin_soporte',
        detalle: 'La instancia todavía no expone las sucursales contratadas (libracore anterior a v1.153.0): hay que actualizarla.',
        precio_base: 39900, precio_adicional: 19950, incluidas: 1, unidad: 'sucursal',
        contratadas: null, activas: null, abono: null,
      }),
    )
    expect(await screen.findByText(/hay que actualizarla/)).toBeInTheDocument()
    expect(screen.queryByLabelText('Sucursales contratadas')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Guardar' })).not.toBeInTheDocument()
  })

  it('si el plan de ESTA instancia no cobra sucursales (aplica: false) no dibuja nada', async () => {
    montarInstancia([PLAN_UNICO, PLAN_SIN_ADICIONAL], () =>
      json({ slug: 'acme', plan: 'basico', aplica: false, estado: 'no_aplica', detalle: '' }),
    )
    await waitFor(() => expect(urlsPedidas().some((u) => u.endsWith('/api/instancias/acme/abono'))).toBe(true))
    expect(screen.getByText('ACME SA')).toBeInTheDocument()
    expect(screen.queryByTestId('sucursales-contratadas')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Sucursales contratadas')).not.toBeInTheDocument()
  })

  it('un producto cuyos planes no cobran sucursales no ve nada nuevo y ni siquiera pide el abono', async () => {
    montarInstancia([PLAN_SIN_ADICIONAL], () => json({}))
    expect(await screen.findByText('ACME SA')).toBeInTheDocument()
    await screen.findByRole('combobox', { name: 'Plan' })
    expect(screen.queryByTestId('sucursales-contratadas')).not.toBeInTheDocument()
    expect(urlsPedidas().some((u) => u.includes('/abono') || u.includes('/sucursales'))).toBe(false)
  })
})

describe('sucursales contratadas en el alta', () => {
  function montarAlta(planes: unknown[]) {
    fetchMock = vi.fn((_url: string, init?: Init) =>
      Promise.resolve(
        init?.method === 'POST'
          ? json({ slug: 'nueva', nombre: 'Nueva SA', domain: '', port: 8090, container: 'c', admin_user: 'admin', admin_password: 'x', plan: 'unico', panel_token: 't', proxy_ok: null }, 201)
          : json({}),
      ),
    )
    vi.stubGlobal('fetch', fetchMock)
    render(<AltaInstancia planes={planes as never} slugsPrevios={[]} recargar={async () => []} />)
  }

  async function abrirYCompletar() {
    const usuario = userEvent.setup({ pointerEventsCheck: 0 })
    await usuario.click(screen.getByRole('button', { name: /nueva instancia/i }))
    await usuario.type(screen.getByLabelText(/nombre del cliente/i), 'Nueva SA')
    await usuario.type(screen.getByLabelText(/^cuit$/i), '20-28993360-4')
    return usuario
  }

  const cuerpoDelAlta = () => {
    const alta = fetchMock.mock.calls.find((c) => (c[1] as Init)?.method === 'POST')
    return alta ? (JSON.parse(String((alta[1] as Init)?.body)) as Record<string, unknown>) : undefined
  }

  it('un producto con un plan único que cobra sucursales pide el número, con 1 por defecto, y lo manda', async () => {
    montarAlta([PLAN_UNICO])
    const usuario = await abrirYCompletar()

    expect(screen.getByLabelText('Sucursales contratadas')).toHaveValue(1)
    await usuario.click(screen.getByRole('button', { name: /crear instancia/i }))

    await waitFor(() => expect(cuerpoDelAlta()).toBeDefined())
    expect(cuerpoDelAlta()!.sucursales_contratadas).toBe(1)
  })

  it('manda el número que se tipeó', async () => {
    montarAlta([PLAN_UNICO])
    const usuario = await abrirYCompletar()
    const campo = screen.getByLabelText('Sucursales contratadas')
    await usuario.clear(campo)
    await usuario.type(campo, '3')
    await usuario.click(screen.getByRole('button', { name: /crear instancia/i }))

    await waitFor(() => expect(cuerpoDelAlta()).toBeDefined())
    expect(cuerpoDelAlta()!.sucursales_contratadas).toBe(3)
  })

  it('explica el precio de cada sucursal de más', async () => {
    montarAlta([PLAN_UNICO])
    await abrirYCompletar()
    expect(screen.getByText(/cada una más suma \$19\.950 por mes \(IVA incluido\)/)).toBeInTheDocument()
  })

  it('con el campo vacío o en 0 no deja crear', async () => {
    montarAlta([PLAN_UNICO])
    const usuario = await abrirYCompletar()
    const campo = screen.getByLabelText('Sucursales contratadas')
    const crear = screen.getByRole('button', { name: /crear instancia/i })

    await usuario.clear(campo)
    expect(crear).toBeDisabled()
    await usuario.type(campo, '0')
    expect(crear).toBeDisabled()
    await usuario.clear(campo)
    await usuario.type(campo, '2')
    expect(crear).toBeEnabled()
  })

  it('un producto cuyos planes no cobran sucursales no muestra el campo ni manda nada', async () => {
    montarAlta([PLAN_SIN_ADICIONAL])
    const usuario = await abrirYCompletar()

    expect(screen.queryByLabelText('Sucursales contratadas')).not.toBeInTheDocument()
    await usuario.click(screen.getByRole('button', { name: /crear instancia/i }))
    await waitFor(() => expect(cuerpoDelAlta()).toBeDefined())
    expect(cuerpoDelAlta()).not.toHaveProperty('sucursales_contratadas')
  })

  it('con varios planes, el campo aparece sólo al elegir el que cobra sucursales', async () => {
    montarAlta([PLAN_UNICO, PLAN_SIN_ADICIONAL])
    const usuario = await abrirYCompletar()
    expect(screen.queryByLabelText('Sucursales contratadas')).not.toBeInTheDocument()

    await usuario.click(screen.getByLabelText('Plan'))
    await usuario.keyboard('plan{Enter}')
    expect(await screen.findByLabelText('Sucursales contratadas')).toHaveValue(1)
  })
})
