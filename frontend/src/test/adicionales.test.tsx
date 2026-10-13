// Los adicionales fuera de la escalera en la pantalla de una instancia y en el alta (ADR-048 de libracore).
//
// Un sí/no se tilda, una cantidad se carga con Guardar, `null` es la baja; el abono sale del backend por líneas y «A cotizar» es lo que todavía no
// tiene precio. Un backend con libracore anterior a v1.162.0 no manda `adicionales` en los planes: la pantalla sigue como siempre (add-ons y
// sucursales), y esta tarjeta no pide nada.
import { configure, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { AltaInstancia } from '../components/AltaInstancia'
import { textoDeLinea } from '../components/Adicionales'
import { Instancia } from '../pages/Instancia'

configure({ asyncUtilTimeout: 5000 })

const INSTANCIA = {
  slug: 'acme', nombre: 'ACME SA', container: 'producto-acme',
  domain: 'acme.test', port: 8081, plan: 'pro', estado: 'running',
  iniciado: '', modulos_activos: null, servicio_estado: 'activo', servicio_mensaje: '',
}

const OFFLINE_DEL_PLAN = { clave: 'offline', label: 'Modo offline', precio: null, unidad: 'sucursal', incluidas: 0, limite: 'sucursales_offline', modulos: ['offline'] }
const RESGUARDO_DEL_PLAN = { clave: 'resguardo_externo', label: 'Resguardo externo', precio: null, unidad: null, incluidas: 0, limite: null, modulos: ['resguardo_externo'] }
const PLAN_PRO = { key: 'pro', label: 'Pro', precio: 69000, modulos: [], adicional: null, adicionales: [OFFLINE_DEL_PLAN, RESGUARDO_DEL_PLAN] }
const PLAN_BASICO = { key: 'basico', label: 'Básico', precio: 27000, modulos: [], adicional: null, adicionales: [OFFLINE_DEL_PLAN, RESGUARDO_DEL_PLAN] }
const PLAN_VIEJO = { key: 'pro', label: 'Pro', precio: 69000, modulos: [], adicional: null }

type Item = Record<string, unknown>

function item(base: Item, extra: Item = {}): Item {
  return { precio: null, unidad: null, incluidas: 0, limite: null, compatible: true, habilitado: false, cantidad: null, usadas: null, editable: true, ...base, ...extra }
}

const OFFLINE = item({ clave: 'offline', label: 'Modo offline', unidad: 'sucursal', limite: 'sucursales_offline', usadas: 1 })
const RESGUARDO = item({ clave: 'resguardo_externo', label: 'Resguardo externo' })

function respuesta(items: Item[], extra: Item = {}) {
  return { slug: 'acme', plan: 'pro', estado: 'ok', detalle: '', adicionales: items, abono: { plan: 'pro', base: 69000, lineas: [], extra: 0, total: 69000, a_cotizar: [] }, ...extra }
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
}

let fetchMock: ReturnType<typeof vi.fn>

type Init = { method?: string; body?: string } | undefined

function montarInstancia(planes: unknown[], adicionales: (metodo: string, init: Init, url: string) => Response) {
  fetchMock = vi.fn((url: string, init?: Init) => {
    const u = String(url)
    if (u.includes('/adicionales')) return Promise.resolve(adicionales(init?.method ?? 'GET', init, u))
    if (u.includes('/addons')) return Promise.resolve(json({ mayorista: false }))
    if (u.includes('/abono')) return Promise.resolve(json({}))
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
const puts = () => fetchMock.mock.calls.filter((c) => (c[1] as Init)?.method === 'PUT' && String(c[0]).includes('/adicionales/'))

beforeEach(() => {
  vi.unstubAllGlobals()
})

describe('adicionales en la pantalla de una instancia', () => {
  it('muestra el sí/no y la cantidad, y reemplaza a los add-ons de siempre', async () => {
    montarInstancia([PLAN_PRO], () => json(respuesta([OFFLINE, RESGUARDO])))

    expect(await screen.findByTestId('adicionales')).toBeInTheDocument()
    expect(screen.getByLabelText(/Modo offline/)).toHaveValue(null)
    expect(screen.getByRole('checkbox')).not.toBeChecked()
    expect(screen.getByText(/en uso 1/)).toBeInTheDocument()
    expect(screen.queryByText('Add-ons')).not.toBeInTheDocument()
    expect(screen.queryByText('mayorista')).not.toBeInTheDocument()
  })

  it('Guardar manda la cantidad y la línea del abono sale «A cotizar»', async () => {
    const usuario = userEvent.setup()
    const contratado = item({ clave: 'offline', label: 'Modo offline', unidad: 'sucursal', habilitado: true, cantidad: 2, usadas: 1 })
    const linea = { clave: 'offline', label: 'Modo offline', unidad: 'sucursal', cantidad: 2, incluidas: 0, cobrables: 2, precio: null, subtotal: null, a_cotizar: true }
    montarInstancia([PLAN_PRO], (metodo) =>
      metodo === 'PUT'
        ? json(respuesta([contratado, RESGUARDO], { abono: { plan: 'pro', base: 69000, lineas: [linea], extra: 0, total: 69000, a_cotizar: ['offline'] } }))
        : json(respuesta([OFFLINE, RESGUARDO])),
    )

    const campo = await screen.findByLabelText(/Modo offline/)
    await usuario.type(campo, '2')
    await usuario.click(screen.getByRole('button', { name: 'Guardar' }))

    await waitFor(() => expect(puts()).toHaveLength(1))
    expect(String(puts()[0][0])).toContain('/api/instancias/acme/adicionales/offline')
    expect(JSON.parse(String((puts()[0][1] as Init)?.body))).toEqual({ cantidad: 2 })
    expect(await screen.findByText('+ Modo offline: 2 sucursales — A cotizar')).toBeInTheDocument()
    expect(screen.getByText(/Total .* \(IVA incluido\) \+ lo que está a cotizar/)).toBeInTheDocument()
    expect(screen.getByLabelText(/Modo offline/)).toHaveValue(2)
  })

  it('«Dar de baja» manda cantidad null', async () => {
    const usuario = userEvent.setup()
    const contratado = item({ clave: 'offline', label: 'Modo offline', unidad: 'sucursal', habilitado: true, cantidad: 2, usadas: 1 })
    montarInstancia([PLAN_PRO], (metodo) => (metodo === 'PUT' ? json(respuesta([OFFLINE, RESGUARDO])) : json(respuesta([contratado, RESGUARDO]))))

    // La pantalla ya tiene un «Dar de baja» (el de la instancia): se busca el de este adicional.
    await usuario.click(within(await screen.findByTestId('adicional-offline')).getByRole('button', { name: 'Dar de baja' }))

    await waitFor(() => expect(puts()).toHaveLength(1))
    expect(JSON.parse(String((puts()[0][1] as Init)?.body))).toEqual({ cantidad: null })
    expect(await screen.findByText('Adicional dado de baja.')).toBeInTheDocument()
  })

  it('tildar un sí/no manda habilitado true', async () => {
    const usuario = userEvent.setup()
    montarInstancia([PLAN_PRO], (metodo) =>
      metodo === 'PUT' ? json(respuesta([OFFLINE, { ...RESGUARDO, habilitado: true }])) : json(respuesta([OFFLINE, RESGUARDO])),
    )

    const chk = await screen.findByRole('checkbox')
    await usuario.click(chk)

    await waitFor(() => expect(puts()).toHaveLength(1))
    expect(String(puts()[0][0])).toContain('/adicionales/resguardo_externo')
    expect(JSON.parse(String((puts()[0][1] as Init)?.body))).toEqual({ habilitado: true })
    await waitFor(() => expect(screen.getByRole('checkbox')).toBeChecked())
  })

  it('avisa cuando hay más en uso que lo contratado', async () => {
    const pasado = item({ clave: 'offline', label: 'Modo offline', unidad: 'sucursal', habilitado: true, cantidad: 1, usadas: 3 })
    montarInstancia([PLAN_PRO], () => json(respuesta([pasado, RESGUARDO])))
    expect(await screen.findByText(/Tiene más en uso que lo contratado/)).toBeInTheDocument()
  })

  it('una instancia que no se pudo leer no dibuja los controles como apagados', async () => {
    const ilegible = (x: Item) => ({ ...x, habilitado: null, cantidad: null, usadas: null, editable: false })
    montarInstancia([PLAN_PRO], () => json(respuesta([ilegible(OFFLINE), ilegible(RESGUARDO)], { estado: 'inalcanzable', detalle: 'La instancia no responde', abono: null })))

    expect(await screen.findByText('La instancia no responde')).toBeInTheDocument()
    expect(screen.getAllByText(/no se pudo leer/)).toHaveLength(2)
    expect(screen.getByRole('checkbox')).toBeDisabled()
    expect(screen.getByLabelText(/Modo offline/)).toBeDisabled()
    expect(screen.queryByTestId('abono-por-lineas')).not.toBeInTheDocument()
  })

  it('una instancia vieja deja tocar los sí/no y bloquea las cantidades, con el motivo', async () => {
    montarInstancia([PLAN_PRO], () =>
      json(respuesta([{ ...OFFLINE, editable: false, usadas: null }, RESGUARDO], { estado: 'sin_soporte', detalle: 'La instancia todavía no expone los adicionales (libracore anterior a v1.162.0)', abono: null })),
    )
    expect(await screen.findByText(/libracore anterior a v1.162.0/)).toBeInTheDocument()
    expect(screen.getByRole('checkbox')).toBeEnabled()
    expect(screen.getByLabelText(/Modo offline/)).toBeDisabled()
    expect(screen.getByText(/No se puede cargar desde acá hasta actualizar la instancia/)).toBeInTheDocument()
  })

  it('un adicional que el plan no admite no se puede contratar, y uno ya contratado se puede dar de baja', async () => {
    const noAdmitido = { ...OFFLINE, compatible: false, editable: false }
    const heredado = item({ clave: 'resguardo_externo', label: 'Resguardo externo', compatible: false, habilitado: true })
    montarInstancia([PLAN_PRO], () => json(respuesta([noAdmitido, heredado])))

    expect(await screen.findByText(/No disponible con este plan/)).toBeInTheDocument()
    expect(screen.getByText(/este plan no lo admite: darlo de baja/)).toBeInTheDocument()
    expect(screen.getByRole('checkbox')).toBeEnabled()
  })

  it('cambiar de plan con un adicional incompatible muestra el 409 del backend', async () => {
    const usuario = userEvent.setup()
    fetchMock = vi.fn((url: string, init?: Init) => {
      const u = String(url)
      if (u.includes('/adicionales')) return Promise.resolve(json(respuesta([OFFLINE, RESGUARDO])))
      if (u.includes('/plan') && init?.method === 'PUT')
        return Promise.resolve(json({ detail: "No se puede pasar al plan 'basico': los adicionales contratados ['offline'] no son compatibles con él. Dalos de baja primero.", incompatibles: ['offline'] }, 409))
      if (u.includes('/api/planes')) return Promise.resolve(json([PLAN_PRO, PLAN_BASICO]))
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

    await usuario.click(await screen.findByRole('combobox', { name: 'Plan' }))
    await usuario.keyboard('básico{Enter}')

    expect(await screen.findByText(/no son compatibles con él/)).toBeInTheDocument()
  })

  it('con un backend sin `adicionales` en los planes sigue la pantalla de siempre y no pide nada nuevo', async () => {
    montarInstancia([PLAN_VIEJO], () => json({}))

    expect(await screen.findByText('Add-ons')).toBeInTheDocument()
    expect(screen.queryByTestId('adicionales')).not.toBeInTheDocument()
    expect(urlsPedidas().some((u) => u.includes('/adicionales'))).toBe(false)
  })
})

describe('textoDeLinea', () => {
  const base = { clave: 'x', label: 'Sucursales', unidad: 'sucursal', cantidad: 3, incluidas: 1, cobrables: 2, precio: 19950, subtotal: 39900, a_cotizar: false }

  it('con precio: cantidad × precio = subtotal', () => {
    expect(textoDeLinea(base)).toBe('Sucursales: 2 sucursales × $ 19.950,00 = $ 39.900,00')
  })

  it('sin precio: a cotizar, en singular con una', () => {
    expect(textoDeLinea({ ...base, cobrables: 1, precio: null, subtotal: null, a_cotizar: true })).toBe('Sucursales: 1 sucursal — A cotizar')
  })

  it('un sí/no sin precio', () => {
    expect(textoDeLinea({ ...base, unidad: null, label: 'Resguardo externo', precio: null, subtotal: null, a_cotizar: true })).toBe('Resguardo externo — A cotizar')
  })
})

describe('adicionales en el alta', () => {
  function montarAlta(planes: unknown[]) {
    fetchMock = vi.fn((_url: string, init?: Init) =>
      Promise.resolve(
        init?.method === 'POST'
          ? json({ slug: 'nueva', nombre: 'Nueva SA', domain: '', port: 8090, container: 'c', admin_user: 'admin', admin_password: 'x', plan: 'basico', panel_token: 't', proxy_ok: null }, 201)
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

  it('el alta ofrece los adicionales del plan y manda sólo los contratados', async () => {
    montarAlta([PLAN_BASICO])
    const usuario = await abrirYCompletar()

    await usuario.type(screen.getByLabelText(/Modo offline/), '2')
    await usuario.click(screen.getByRole('checkbox', { name: /Resguardo externo/ }))
    await usuario.click(screen.getByRole('button', { name: /crear instancia/i }))

    await waitFor(() => expect(cuerpoDelAlta()).toBeDefined())
    expect(cuerpoDelAlta()!.adicionales).toEqual({ offline: 2, resguardo_externo: true })
  })

  it('sin elegir ninguno no manda `adicionales`', async () => {
    montarAlta([PLAN_BASICO])
    const usuario = await abrirYCompletar()
    await usuario.click(screen.getByRole('button', { name: /crear instancia/i }))
    await waitFor(() => expect(cuerpoDelAlta()).toBeDefined())
    expect(cuerpoDelAlta()).not.toHaveProperty('adicionales')
  })

  it('una cantidad en 0 no deja crear', async () => {
    montarAlta([PLAN_BASICO])
    const usuario = await abrirYCompletar()
    await usuario.type(screen.getByLabelText(/Modo offline/), '0')
    expect(screen.getByRole('button', { name: /crear instancia/i })).toBeDisabled()
  })

  it('un producto sin adicionales no muestra la sección', async () => {
    montarAlta([PLAN_VIEJO])
    await abrirYCompletar()
    expect(screen.queryByTestId('alta-adicionales')).not.toBeInTheDocument()
  })
})
