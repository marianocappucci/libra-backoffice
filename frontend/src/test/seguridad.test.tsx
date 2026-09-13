// La pantalla de Seguridad: el interruptor de doble factor (TOTP).
//
// El backend todavía no existe (contrato en el prompt de la tarea) — todo acá
// es contra mocks de `fetch`. Lo que importa fijar:
//   - encender no activa nada solo: dispara `iniciar` y muestra QR + secreto,
//     con el aviso de que hace falta confirmar.
//   - confirmar manda el código tal cual se escribió y, si sale bien, el QR y
//     el secreto desaparecen del DOM (y de paso, del estado de React — no hay
//     forma de mostrarlos de nuevo sin un `iniciar` nuevo).
//   - apagar NO llama a nada hasta que se confirma con un código: primero pide
//     el código, después pega a `desactivar`.
//   - `origen: "entorno"` y `enrolable: false` deshabilitan el interruptor,
//     cada uno con su propia nota.
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { Seguridad } from '../pages/Seguridad'

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status, headers: { 'content-type': 'application/json' },
  })
}

type Init = { method?: string; body?: string } | undefined

const QR = 'data:image/svg+xml;base64,AAAA'
const INICIADO = { secreto: 'ABCDEFGH', uri: 'otpauth://totp/Backoffice?secret=ABCDEFGH', qr: QR }

/** Servidor mock con memoria: `confirmar`/`desactivar` cambian lo que el
 *  próximo GET devuelve, como haría el backend real. `overrides` pisa una
 *  ruta puntual (p.ej. para que `confirmar` conteste 400). */
function montar(
  inicial: { activo: boolean; origen: 'entorno' | 'archivo' | null; enrolable: boolean },
  overrides: Record<string, (init: Init) => Promise<Response>> = {},
) {
  let estado = { ...inicial }
  const fetchMock = vi.fn((url: string, init: Init) => {
    const u = String(url)
    const metodo = init?.method ?? 'GET'
    const clave = `${metodo} ${u}`
    if (overrides[clave]) return overrides[clave](init)

    if (metodo === 'GET' && u.endsWith('/api/seguridad/totp')) {
      return Promise.resolve(json(estado))
    }
    if (metodo === 'POST' && u.endsWith('/api/seguridad/totp/iniciar')) {
      return Promise.resolve(json(INICIADO))
    }
    if (metodo === 'POST' && u.endsWith('/api/seguridad/totp/confirmar')) {
      estado = { ...estado, activo: true, origen: 'archivo' }
      return Promise.resolve(json({ activo: true }))
    }
    if (metodo === 'POST' && u.endsWith('/api/seguridad/totp/desactivar')) {
      estado = { ...estado, activo: false, origen: null }
      return Promise.resolve(json({ activo: false }))
    }
    return Promise.resolve(json({}))
  })
  vi.stubGlobal('fetch', fetchMock)
  render(<Seguridad />)
  return fetchMock
}

const usuario = () => userEvent.setup({ pointerEventsCheck: 0 })

function cuerpoDe(llamada: unknown[]): Record<string, unknown> {
  return JSON.parse(String((llamada[1] as Init)?.body))
}

describe('Seguridad — doble factor (TOTP)', () => {
  it('inactivo: encender llama a iniciar y muestra el QR y el secreto agrupado', async () => {
    const fetchMock = montar({ activo: false, origen: null, enrolable: true })
    const u = usuario()

    const interruptor = await screen.findByRole('switch', { name: /doble factor/i })
    expect(interruptor).not.toBeChecked()
    await u.click(interruptor)

    await waitFor(() => {
      expect(fetchMock.mock.calls.some(
        (c) => String(c[0]).endsWith('/api/seguridad/totp/iniciar') && (c[1] as Init)?.method === 'POST',
      )).toBe(true)
    })

    const qr = await screen.findByRole('img', { name: /código qr/i })
    expect(qr).toHaveAttribute('src', QR)
    expect(screen.getByText('ABCD EFGH')).toBeInTheDocument()
    expect(screen.getByText(/no queda activo/i)).toBeInTheDocument()
  })

  it('confirmar manda el código y oculta el QR', async () => {
    const fetchMock = montar({ activo: false, origen: null, enrolable: true })
    const u = usuario()

    await u.click(await screen.findByRole('switch', { name: /doble factor/i }))
    await screen.findByRole('img', { name: /código qr/i })

    await u.type(screen.getByLabelText(/código del autenticador/i), '123456')
    await u.click(screen.getByRole('button', { name: /^confirmar$/i }))

    await waitFor(() => {
      const post = fetchMock.mock.calls.find(
        (c) => String(c[0]).endsWith('/api/seguridad/totp/confirmar') && (c[1] as Init)?.method === 'POST',
      )
      expect(post).toBeTruthy()
      expect(cuerpoDe(post!)).toEqual({ codigo: '123456' })
    })

    expect(screen.queryByRole('img', { name: /código qr/i })).not.toBeInTheDocument()
    expect(screen.queryByText('ABCD EFGH')).not.toBeInTheDocument()
    expect(await screen.findByText(/desde el próximo inicio de sesión/i)).toBeInTheDocument()
  })

  it('un código inválido muestra el detail del backend', async () => {
    montar({ activo: false, origen: null, enrolable: true }, {
      'POST /api/seguridad/totp/confirmar': () =>
        Promise.resolve(json({ detail: 'El código no es válido.' }, 400)),
    })
    const u = usuario()

    await u.click(await screen.findByRole('switch', { name: /doble factor/i }))
    await screen.findByRole('img', { name: /código qr/i })
    await u.type(screen.getByLabelText(/código del autenticador/i), '000000')
    await u.click(screen.getByRole('button', { name: /^confirmar$/i }))

    expect(await screen.findByText('El código no es válido.')).toBeInTheDocument()
    // Y el QR sigue ahí: un 400 no es una confirmación exitosa.
    expect(screen.getByRole('img', { name: /código qr/i })).toBeInTheDocument()
  })

  it('activo: apagar pide un código y recién ahí llama a desactivar', async () => {
    const fetchMock = montar({ activo: true, origen: 'archivo', enrolable: true })
    const u = usuario()

    const interruptor = await screen.findByRole('switch', { name: /doble factor/i })
    expect(interruptor).toBeChecked()
    await u.click(interruptor)

    // Apagar el interruptor no pega a nada todavía: sólo abre el pedido de código.
    const input = await screen.findByLabelText(/código del autenticador, para desactivar/i)
    expect(fetchMock.mock.calls.some((c) => (c[1] as Init)?.method === 'POST')).toBe(false)

    await u.type(input, '654321')
    await u.click(screen.getByRole('button', { name: /^desactivar$/i }))

    await waitFor(() => {
      const post = fetchMock.mock.calls.find(
        (c) => String(c[0]).endsWith('/api/seguridad/totp/desactivar') && (c[1] as Init)?.method === 'POST',
      )
      expect(post).toBeTruthy()
      expect(cuerpoDe(post!)).toEqual({ codigo: '654321' })
    })
    expect(await screen.findByText(/desactivado/i)).toBeInTheDocument()
  })

  it('origen "entorno" deshabilita el interruptor', async () => {
    montar({ activo: true, origen: 'entorno', enrolable: true })

    const interruptor = await screen.findByRole('switch', { name: /doble factor/i })
    expect(interruptor).toBeDisabled()
    expect(screen.getByText(/ADMIN_PANEL_TOTP_SECRET/)).toBeInTheDocument()
  })

  it('sin dónde guardar el secreto deshabilita el interruptor', async () => {
    montar({ activo: false, origen: null, enrolable: false })

    const interruptor = await screen.findByRole('switch', { name: /doble factor/i })
    expect(interruptor).toBeDisabled()
    expect(screen.getByText(/ADMIN_PANEL_ESTADO_PATH/)).toBeInTheDocument()
  })
})
