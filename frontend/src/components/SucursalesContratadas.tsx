// Las sucursales que el cliente CONTRATÓ, y lo que eso cuesta por mes (ADR-041 de libracore).
//
// El plan único de VentaLibra incluye UNA sucursal; cada una más suma un adicional. Se cobra lo CONTRATADO, no lo usado, y ese número vive en la
// INSTANCIA (es lo que le permite bloquear el alta de una sucursal de más): acá se lee con `GET /api/instancias/{slug}/abono` y se carga con
// `PUT .../sucursales`. El abono lo calcula el backend con `libracore.abono.calcular_abono`; esta pantalla no repite la cuenta.
//
// Sin dato cargado la instancia NO tiene límite, y se dice «Sin cargar» — nunca «1»: son cosas distintas (una contratada limita, sin cargar no).
//
// Se monta sólo si algún plan del producto declara `adicional` (ver `Instancia.tsx`); si el plan de ESTA instancia no cobra sucursales, el backend
// contesta `aplica: false` y esta tarjeta no dibuja nada.
import { useCallback, useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

import { ApiError, backoffice, type Abono } from '../api'

type Props = {
  slug: string
  /** El plan de la instancia: cuando cambia, el abono se vuelve a pedir. */
  plan: string
  /** Un padre ocupado (cambiando el plan, por ejemplo) bloquea el guardado. */
  deshabilitado?: boolean
}

function plata(n: number): string {
  return `$${n.toLocaleString('es-AR')}`
}

function describirError(err: unknown): string {
  if (err instanceof ApiError) return err.detail
  return 'Error de conexión.'
}

/** «Plan único $39.900 + 2 sucursales adicionales × $19.950 = $79.800 (IVA incluido)». */
function lineaDelAbono(a: Abono): string {
  const t = a.abono
  if (!t) return ''
  const unidad = t.adicionales === 1 ? 'sucursal adicional' : 'sucursales adicionales'
  return `${a.plan_label ?? a.plan} ${plata(t.base)} + ${t.adicionales} ${unidad} × ${plata(t.precio_adicional)} = ${plata(t.total)} (IVA incluido)`
}

export function SucursalesContratadas({ slug, plan, deshabilitado = false }: Props) {
  const [abono, setAbono] = useState<Abono | null>(null)
  const [valor, setValor] = useState('')
  const [guardando, setGuardando] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)

  const aplicar = useCallback((a: Abono) => {
    setAbono(a)
    setValor(a.contratadas != null ? String(a.contratadas) : '')
  }, [])

  useEffect(() => {
    let vigente = true
    setError(null)
    setAviso(null)
    backoffice
      .abono(slug)
      .then((a) => vigente && aplicar(a))
      .catch((err) => vigente && setError(describirError(err)))
    return () => {
      vigente = false
    }
  }, [slug, plan, aplicar])

  async function guardar(contratadas: number | null) {
    setGuardando(true)
    setError(null)
    setAviso(null)
    try {
      aplicar(await backoffice.cargarSucursales(slug, contratadas))
      setAviso(contratadas === null ? 'Sin límite: se quitó el dato de la instancia.' : 'Sucursales contratadas guardadas.')
    } catch (err) {
      setError(describirError(err))
    } finally {
      setGuardando(false)
    }
  }

  // Otro producto, o un plan que no cobra sucursales: no hay nada que mostrar (y tampoco se muestra un error si aún no cargó).
  if (abono && !abono.aplica) return null
  if (!abono) return error ? <p className="text-sm font-medium text-destructive">{error}</p> : null

  const numero = Number(valor)
  const valido = valor.trim() !== '' && Number.isInteger(numero) && numero >= 1
  const sinCambios = valido && numero === abono.contratadas
  const ok = abono.estado === 'ok'
  const contratadas = abono.contratadas ?? null
  const activas = abono.activas ?? null

  return (
    <div className="space-y-2" data-testid="sucursales-contratadas">
      <span className="text-sm text-muted-foreground">Sucursales y abono</span>

      {ok ? (
        <>
          <p className="text-sm">
            {contratadas === null ? (
              <>
                {abono.plan_label ?? abono.plan} {plata(abono.precio_base ?? 0)} (IVA incluido) — cada sucursal adicional suma{' '}
                {plata(abono.precio_adicional ?? 0)}.
              </>
            ) : (
              lineaDelAbono(abono)
            )}
          </p>
          <p className="text-sm text-muted-foreground">
            Activas {activas ?? '—'} de {contratadas ?? 'Sin cargar'} contratadas
            {contratadas === null && ' (sin límite)'}.
          </p>
          {contratadas !== null && activas !== null && activas > contratadas && (
            <p className="text-sm font-medium text-destructive">
              Tiene más sucursales activas que las contratadas: no puede sumar otra, y conviene regularizar el contrato.
            </p>
          )}

          <form
            className="flex flex-wrap items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              if (valido && !sinCambios) void guardar(numero)
            }}
          >
            <div className="grid gap-1">
              <Label htmlFor="sucursales-contratadas">Sucursales contratadas</Label>
              <Input
                id="sucursales-contratadas"
                type="number"
                min={1}
                step={1}
                className="w-40"
                value={valor}
                disabled={guardando || deshabilitado}
                onChange={(e) => setValor(e.target.value)}
                placeholder="Sin cargar"
              />
            </div>
            <Button type="submit" size="sm" disabled={!valido || sinCambios || guardando || deshabilitado}>
              {guardando ? 'Guardando…' : 'Guardar'}
            </Button>
            {contratadas !== null && (
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={guardando || deshabilitado}
                onClick={() => void guardar(null)}
              >
                Quitar límite
              </Button>
            )}
          </form>
        </>
      ) : (
        <p className="text-sm text-muted-foreground">{abono.detalle || 'No se pudo leer lo contratado.'}</p>
      )}

      {aviso && <p className="text-sm text-muted-foreground">{aviso}</p>}
      {error && <p className="text-sm font-medium text-destructive">{error}</p>}
    </div>
  )
}
