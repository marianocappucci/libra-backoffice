// Los adicionales fuera de la escalera de planes de una instancia, y el abono por líneas (ADR-048 de libracore).
//
// Un adicional se contrata aparte del plan y sobrevive a cambiarlo: un sí/no (el resguardo externo) o una cantidad (sucursales; sucursales con
// offline). Lo contratado y lo usado viven en la INSTANCIA —es lo que le permite hacer cumplir el tope—, así que acá se lee con
// `GET /api/instancias/{slug}/adicionales` y se carga con `PUT .../adicionales/{clave}` (`null` es la baja). El abono lo arma el backend
// (`libracore.adicionales`): el plan más una línea por adicional contratado, con «A cotizar» donde todavía no hay precio. Esta pantalla no repite
// la cuenta.
//
// 🔑 `habilitado`/`cantidad: null` es «no se pudo leer», no «apagado»: se dice, y el control queda deshabilitado. Una instancia anterior a
// libracore v1.162.0 sólo deja prender y apagar los sí/no (por docker exec); las cantidades se muestran bloqueadas con el motivo.
//
// Se monta sólo si algún plan del producto declara `adicionales` (ver `Instancia.tsx`); los demás productos no ven nada nuevo.
import { useCallback, useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { formatoMoneda } from 'libra-ui/formatos'

import { ApiError, backoffice, type AdicionalDeInstancia, type Adicionales as TAdicionales, type LineaDeAbono } from '../api'

type Props = {
  slug: string
  /** El plan de la instancia: cuando cambia, todo se vuelve a pedir (las incluidas y los compatibles son del plan). */
  plan: string
  /** Un padre ocupado (cambiando el plan, por ejemplo) bloquea el guardado. */
  deshabilitado?: boolean
}

function describirError(err: unknown): string {
  if (err instanceof ApiError) return err.detail
  return 'Error de conexión.'
}

function precioDe(a: { precio: number | null }): string {
  return a.precio === null ? 'A cotizar' : formatoMoneda(a.precio)
}

/** «Sucursales: 3 × $ 19.950,00 = $ 39.900,00» o «Modo offline: 2 sucursales — A cotizar». */
export function textoDeLinea(ln: LineaDeAbono): string {
  const cantidad = ln.unidad ? `${ln.cobrables} ${ln.unidad === 'sucursal' ? (ln.cobrables === 1 ? 'sucursal' : 'sucursales') : ln.unidad}` : ''
  if (ln.a_cotizar) return `${ln.label}${cantidad ? `: ${cantidad}` : ''} — A cotizar`
  return `${ln.label}${cantidad ? `: ${cantidad} × ${formatoMoneda(ln.precio ?? 0)}` : ''} = ${formatoMoneda(ln.subtotal ?? 0)}`
}

function Fila({ a, ocupado, onGuardar }: {
  a: AdicionalDeInstancia
  ocupado: boolean
  onGuardar: (clave: string, cuerpo: { habilitado: boolean | null } | { cantidad: number | null }) => Promise<void>
}) {
  const [valor, setValor] = useState(a.cantidad != null ? String(a.cantidad) : '')
  useEffect(() => setValor(a.cantidad != null ? String(a.cantidad) : ''), [a.cantidad])

  const sinLeer = a.habilitado === null && a.cantidad === null
  const contratado = a.unidad ? a.cantidad !== null || a.habilitado === true : a.habilitado === true
  const bloqueado = ocupado || !a.editable
  const noDisponible = !a.compatible && !contratado

  if (!a.unidad) {
    return (
      <label className="flex flex-wrap items-center gap-2 text-sm" data-testid={`adicional-${a.clave}`}>
        <Checkbox
          checked={a.habilitado === true}
          disabled={bloqueado || sinLeer || noDisponible}
          onCheckedChange={(v) => void onGuardar(a.clave, { habilitado: v === true })}
        />
        {a.label}
        <span className="text-xs text-muted-foreground">{precioDe(a)}</span>
        {sinLeer && <span className="text-xs text-muted-foreground">(no se pudo leer)</span>}
        {noDisponible && <span className="text-xs text-muted-foreground">(no disponible con este plan)</span>}
        {!a.compatible && contratado && (
          <span className="text-xs font-medium text-destructive">(este plan no lo admite: darlo de baja)</span>
        )}
      </label>
    )
  }

  const numero = Number(valor)
  const valido = valor.trim() !== '' && Number.isInteger(numero) && numero >= 1
  const sinCambios = valido && numero === a.cantidad
  const excedido = a.cantidad !== null && a.usadas !== null && a.usadas > a.cantidad
  return (
    <div className="space-y-1" data-testid={`adicional-${a.clave}`}>
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          if (valido && !sinCambios) void onGuardar(a.clave, { cantidad: numero })
        }}
      >
        <div className="grid gap-1">
          <Label htmlFor={`adicional-${a.clave}-cantidad`}>
            {a.label} ({precioDe(a)}{a.incluidas ? `; el plan incluye ${a.incluidas}` : ''})
          </Label>
          <Input
            id={`adicional-${a.clave}-cantidad`}
            type="number"
            min={1}
            step={1}
            className="w-40"
            value={valor}
            disabled={bloqueado || noDisponible}
            onChange={(e) => setValor(e.target.value)}
            placeholder="Sin contratar"
          />
        </div>
        <Button type="submit" size="sm" disabled={!valido || sinCambios || bloqueado || noDisponible}>
          Guardar
        </Button>
        {contratado && (
          <Button type="button" size="sm" variant="outline" disabled={bloqueado} onClick={() => void onGuardar(a.clave, { cantidad: null })}>
            Dar de baja
          </Button>
        )}
      </form>
      <p className="text-sm text-muted-foreground">
        {sinLeer ? '(no se pudo leer)' : `Contratadas ${a.cantidad ?? (contratado ? 'sin cargar' : '—')}; en uso ${a.usadas ?? '—'}.`}
        {noDisponible && ' No disponible con este plan.'}
        {!a.editable && !noDisponible && !sinLeer && ' No se puede cargar desde acá hasta actualizar la instancia.'}
      </p>
      {excedido && (
        <p className="text-sm font-medium text-destructive">
          Tiene más en uso que lo contratado: no puede sumar otra, y conviene regularizar el contrato.
        </p>
      )}
    </div>
  )
}

export function Adicionales({ slug, plan, deshabilitado = false }: Props) {
  const [datos, setDatos] = useState<TAdicionales | null>(null)
  const [guardando, setGuardando] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)

  useEffect(() => {
    let vigente = true
    setError(null)
    setAviso(null)
    backoffice
      .adicionales(slug)
      .then((d) => vigente && setDatos(d))
      .catch((err) => vigente && setError(describirError(err)))
    return () => {
      vigente = false
    }
  }, [slug, plan])

  const guardar = useCallback(
    async (clave: string, cuerpo: { habilitado: boolean | null } | { cantidad: number | null }) => {
      setGuardando(true)
      setError(null)
      setAviso(null)
      try {
        setDatos(await backoffice.cargarAdicional(slug, clave, cuerpo))
        const baja = Object.values(cuerpo)[0] === null || Object.values(cuerpo)[0] === false
        setAviso(baja ? 'Adicional dado de baja.' : 'Adicional guardado.')
      } catch (err) {
        setError(describirError(err))
      } finally {
        setGuardando(false)
      }
    },
    [slug],
  )

  if (!datos) return error ? <p className="text-sm font-medium text-destructive">{error}</p> : null
  if (datos.estado === 'no_aplica' || datos.adicionales.length === 0) return null

  const abono = datos.abono
  return (
    <div className="space-y-3" data-testid="adicionales">
      <span className="text-sm text-muted-foreground">Adicionales</span>

      {datos.estado !== 'ok' && <p className="text-sm text-muted-foreground">{datos.detalle || 'No se pudo leer lo contratado.'}</p>}

      <div className="space-y-3">
        {datos.adicionales.map((a) => (
          <Fila key={a.clave} a={a} ocupado={guardando || deshabilitado} onGuardar={guardar} />
        ))}
      </div>

      {abono && (
        <div className="space-y-1 text-sm" data-testid="abono-por-lineas">
          <p>
            Anexo I — {datos.plan}: {abono.base === null ? 'sin precio' : formatoMoneda(abono.base)}
          </p>
          {abono.lineas.map((ln) => (
            <p key={ln.clave}>+ {textoDeLinea(ln)}</p>
          ))}
          {abono.total !== null && (
            <p className="font-medium">
              Total {formatoMoneda(abono.total)} (IVA incluido)
              {abono.a_cotizar.length > 0 && ' + lo que está a cotizar'}
            </p>
          )}
        </div>
      )}

      {aviso && <p className="text-sm text-muted-foreground">{aviso}</p>}
      {error && <p className="text-sm font-medium text-destructive">{error}</p>}
    </div>
  )
}
