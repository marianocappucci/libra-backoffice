// «Apariencia»: los colores de la suite. Lo que importa fijar:
//   - la lista de colores sale del kit (`COLORES_DE_TEMA`), no está escrita en la pantalla;
//   - no se puede guardar un color inválido ni un fondo sobre el que ningún texto se lee (el botón queda apagado y se dice por qué);
//   - guardar manda el tema COMPLETO y normalizado, y la pantalla cuenta qué le pasó a cada instancia (incluidas las que fallaron);
//   - restaurar manda `{}` (las instancias vuelven a los colores de siempre) y «Reaplicar» vuelve a empujar el guardado.
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { Apariencia } from '../pages/Apariencia'

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
}

type Init = { method?: string; body?: string } | undefined

const OK = (slug: string, nombre: string, estado: string, detalle = '') => ({ slug, nombre, estado, detalle })

function montar(opciones: { tema?: Record<string, string>; estado?: unknown[]; resultados?: unknown[] } = {}) {
  const llamadas: { metodo: string; url: string; cuerpo: unknown }[] = []
  let guardado = opciones.tema ?? {}
  vi.stubGlobal('fetch', vi.fn((url: string, init: Init) => {
    const u = String(url)
    const metodo = init?.method ?? 'GET'
    llamadas.push({ metodo, url: u, cuerpo: init?.body ? JSON.parse(init.body) : undefined })
    if (u.endsWith('/api/apariencia') && metodo === 'GET') return Promise.resolve(json({ tema: guardado }))
    if (u.endsWith('/api/apariencia') && metodo === 'PUT') {
      guardado = JSON.parse(String(init?.body)).tema
      return Promise.resolve(json({ tema: guardado, resultados: opciones.resultados ?? [OK('acme', 'ACME SA', 'aplicada')] }))
    }
    if (u.endsWith('/api/apariencia/aplicar')) {
      return Promise.resolve(json({ tema: guardado, resultados: [OK('acme', 'ACME SA', 'aplicada')] }))
    }
    if (u.endsWith('/api/apariencia/estado')) {
      return Promise.resolve(json({ tema: guardado, instancias: opciones.estado ?? [OK('acme', 'ACME SA', 'al_dia')] }))
    }
    return Promise.resolve(json({}))
  }))
  render(<Apariencia />)
  return llamadas
}

const boton = (nombre: RegExp) => screen.findByRole('button', { name: nombre })

describe('Apariencia', () => {
  it('arma una fila por cada color del kit, con su ayuda, y todos arrancan «de siempre»', async () => {
    montar()
    expect(await screen.findByLabelText('Ítem activo del menú: fondo')).toHaveValue('#ecfdf5')
    expect(screen.getByLabelText('Ítem activo del menú: borde')).toHaveValue('#5ee9b5')
    // El éxito y la franja del POS tienen valor de siempre; el acento y la barra lateral son «el de cada producto» y el campo queda vacío.
    expect(screen.getByLabelText('Color de éxito')).toHaveValue('#059669')
    expect(screen.getByLabelText('Encabezado del POS: inicio')).toHaveValue('#0284c7')
    expect(screen.getByLabelText('Acento principal')).toHaveValue('')
    expect(screen.getByLabelText('Barra lateral: fondo')).toHaveValue('')
    expect(screen.getAllByText('De siempre')).toHaveLength(5)
    expect(screen.getAllByText('El de cada producto')).toHaveLength(2)
  })

  it('un color nuevo se manda con su clave y un acento casi negro se rechaza antes de guardar', async () => {
    const user = userEvent.setup()
    const llamadas = montar({ resultados: [OK('acme', 'ACME SA', 'aplicada')] })
    const acento = await screen.findByLabelText('Acento principal')
    await user.type(acento, '#171717')
    expect(await screen.findByRole('alert')).toHaveTextContent(/no se distingue del fondo/)
    expect(await boton(/Guardar y aplicar/)).toBeDisabled()
    await user.clear(acento)
    await user.type(acento, '#0F766E')
    await user.click(await boton(/Guardar y aplicar/))
    await waitFor(() => expect(llamadas.some((l) => l.metodo === 'PUT')).toBe(true))
    expect(llamadas.find((l) => l.metodo === 'PUT')!.cuerpo).toEqual({ tema: { acento: '#0f766e' } })
  })

  it('guardar manda el tema normalizado a minúsculas y cuenta qué pasó con cada instancia', async () => {
    const user = userEvent.setup()
    const llamadas = montar({ resultados: [OK('acme', 'ACME SA', 'aplicada'), OK('beta', 'Beta SRL', 'inalcanzable', 'sin respuesta')] })
    const fondo = await screen.findByLabelText('Ítem activo del menú: fondo')
    await user.clear(fondo)
    await user.type(fondo, '#FDF2F8')
    await user.click(await boton(/Guardar y aplicar/))
    await waitFor(() => expect(llamadas.some((l) => l.metodo === 'PUT')).toBe(true))
    expect(llamadas.find((l) => l.metodo === 'PUT')?.cuerpo).toEqual({ tema: { menuActivoFondo: '#fdf2f8' } })
    const resultado = (await screen.findByText('Resultado')).closest('div[data-slot="card"]') as HTMLElement
    expect(within(resultado).getByText('Aplicada')).toBeInTheDocument()
    expect(within(resultado).getByText('No contesta')).toBeInTheDocument()
    expect(await screen.findByText(/1 instancia no lo recibió/)).toBeInTheDocument()
  })

  it('un color que no es un color apaga el guardado y lo dice', async () => {
    const user = userEvent.setup()
    const llamadas = montar()
    const borde = await screen.findByLabelText('Ítem activo del menú: borde')
    await user.clear(borde)
    await user.type(borde, 'verde')
    expect(await screen.findByRole('alert')).toHaveTextContent(/no es un color/)
    expect(await boton(/Guardar y aplicar/)).toBeDisabled()
    expect(llamadas.some((l) => l.metodo === 'PUT')).toBe(false)
  })

  it('un fondo sobre el que ningún texto se lee no se puede guardar', async () => {
    const user = userEvent.setup()
    montar()
    const fondo = await screen.findByLabelText('Ítem activo del menú: fondo')
    await user.clear(fondo)
    await user.type(fondo, '#7b7b7b')
    expect(await screen.findByRole('alert')).toHaveTextContent(/ningún texto se lee/)
    expect(await boton(/Guardar y aplicar/)).toBeDisabled()
  })

  it('restaurar los valores de siempre manda un tema vacío al guardar', async () => {
    const user = userEvent.setup()
    const llamadas = montar({ tema: { menuActivoFondo: '#fdf2f8' } })
    expect(await screen.findByText('Personalizado')).toBeInTheDocument()
    await user.click(await boton(/Restaurar los valores de siempre/))
    expect(await screen.findByText(/Se van a quitar todos los colores personalizados/)).toBeInTheDocument()
    await user.click(await boton(/Guardar y aplicar/))
    await waitFor(() => expect(llamadas.some((l) => l.metodo === 'PUT')).toBe(true))
    expect(llamadas.find((l) => l.metodo === 'PUT')?.cuerpo).toEqual({ tema: {} })
  })

  it('muestra el estado de cada instancia y «Reaplicar a todas» vuelve a empujar lo guardado', async () => {
    const user = userEvent.setup()
    const llamadas = montar({
      tema: { menuActivoFondo: '#fdf2f8' },
      estado: [OK('acme', 'ACME SA', 'al_dia'), OK('beta', 'Beta SRL', 'desfasada'), OK('vieja', 'Vieja SA', 'sin_soporte', 'actualizar')],
    })
    expect(await screen.findByText('Al día')).toBeInTheDocument()
    expect(screen.getByText('Desfasada')).toBeInTheDocument()
    expect(screen.getByText('Hay que actualizarla')).toBeInTheDocument()
    await user.click(await boton(/Reaplicar a todas/))
    await waitFor(() => expect(llamadas.some((l) => l.metodo === 'POST' && l.url.endsWith('/aplicar'))).toBe(true))
    expect(await screen.findByText(/Se volvió a aplicar/)).toBeInTheDocument()
  })

  it('un error del servidor se muestra y no rompe la pantalla', async () => {
    const user = userEvent.setup()
    montar()
    const fondo = await screen.findByLabelText('Ítem activo del menú: fondo')
    await user.clear(fondo)
    await user.type(fondo, '#FDF2F8')
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(json({ detail: 'Falló el guardado.' }, 500))))
    await user.click(await boton(/Guardar y aplicar/))
    expect(await screen.findByText('Falló el guardado.')).toBeInTheDocument()
  })
})
