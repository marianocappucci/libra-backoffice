// «Apariencia»: los colores de la suite. Se eligen acá y el backoffice los empuja a TODAS las instancias del producto (ADR-007 de
// `libra-ui`; cada instancia los guarda y los sirve ella misma, `libracore.tema_router`, ADR-012).
//
// La lista de colores NO está escrita acá: sale de `COLORES_DE_TEMA` de `libra-ui/tema`, la misma que lee la instancia y la SPA. Agregar un
// color al kit lo agrega a esta pantalla sin tocarla. Lo que sí hace la pantalla es no dejar mandar nada inválido (`validarTema`: un fondo
// sobre el que ningún texto se lee no pasa) y mostrar, antes de guardar, cómo queda.
import { useCallback, useEffect, useMemo, useState } from 'react'
import { RotateCcw, Save, RefreshCw } from 'lucide-react'
import { COLORES_DE_TEMA, textoSobre, validarTema } from 'libra-ui/tema'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

import { ApiError, backoffice, type EstadoDeTema, type ResultadoDeTema, type Tema } from '../api'

function describirError(err: unknown): string {
  if (err instanceof ApiError) return err.detail
  return 'Error de conexión.'
}

const ETIQUETA: Record<EstadoDeTema, { texto: string; mala: boolean }> = {
  aplicada: { texto: 'Aplicada', mala: false },
  al_dia: { texto: 'Al día', mala: false },
  desfasada: { texto: 'Desfasada', mala: true },
  detenida: { texto: 'Detenida', mala: false },
  inalcanzable: { texto: 'No contesta', mala: true },
  sin_soporte: { texto: 'Hay que actualizarla', mala: true },
  rechazada: { texto: 'Rechazada', mala: true },
  error: { texto: 'Error', mala: true },
}

function Estado({ r }: { r: ResultadoDeTema }) {
  const e = ETIQUETA[r.estado]
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-b py-2 last:border-0">
      <div className="min-w-0">
        <p className="truncate text-sm font-medium">{r.nombre}</p>
        {r.detalle && <p className="truncate text-xs text-muted-foreground">{r.detalle}</p>}
      </div>
      <Badge variant={e.mala ? 'destructive' : 'outline'}>{e.texto}</Badge>
    </div>
  )
}

/** Cómo queda el ítem activo del menú con los colores elegidos: sobre una barra clara y sobre una oscura (el texto se calcula, así que
 *  se lee en las dos). */
function Vista({ fondo, borde }: { fondo: string; borde: string }) {
  const texto = textoSobre(fondo)
  const item = (activo: boolean, nombre: string) => (
    <div
      className="rounded-md px-3 py-2 text-sm"
      style={activo ? { backgroundColor: fondo, color: texto, boxShadow: `inset 0 0 0 1px ${borde}` } : undefined}
    >
      {nombre}
    </div>
  )
  return (
    <div className="grid gap-3 sm:grid-cols-2" aria-label="Vista previa del menú">
      <div className="space-y-1 rounded-lg border bg-white p-3 text-neutral-700">
        {item(false, 'Ventas')}
        {item(true, 'Ítem activo')}
        {item(false, 'Clientes')}
      </div>
      <div className="space-y-1 rounded-lg border bg-neutral-900 p-3 text-neutral-200">
        {item(false, 'Ventas')}
        {item(true, 'Ítem activo')}
        {item(false, 'Clientes')}
      </div>
    </div>
  )
}

export function Apariencia() {
  const [guardado, setGuardado] = useState<Tema>({})
  // Lo que se está editando. Una clave AUSENTE usa el color de siempre.
  const [valores, setValores] = useState<Tema>({})
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [ocupado, setOcupado] = useState(false)
  const [resultados, setResultados] = useState<ResultadoDeTema[] | null>(null)
  const [estado, setEstado] = useState<ResultadoDeTema[] | null>(null)

  const leerEstado = useCallback(async () => {
    try {
      setEstado((await backoffice.apariencia.estado()).instancias)
    } catch {
      setEstado(null)
    }
  }, [])

  useEffect(() => {
    backoffice.apariencia
      .leer()
      .then(({ tema }) => {
        setGuardado(tema)
        setValores(tema)
      })
      .catch((err) => setError(describirError(err)))
      .finally(() => setCargando(false))
    void leerEstado()
  }, [leerEstado])

  const { tema: limpio, errores } = useMemo(() => validarTema(valores), [valores])
  const hayErrores = Object.keys(errores).length > 0
  const cambios = JSON.stringify(limpio) !== JSON.stringify(guardado)
  const color = (clave: string) => limpio[clave as keyof typeof limpio] ?? COLORES_DE_TEMA.find((d) => d.clave === clave)!.porDefecto

  function poner(clave: string, valor: string) {
    setAviso(null)
    setValores((v) => ({ ...v, [clave]: valor }))
  }

  function usarElDeSiempre(clave: string) {
    setValores((v) => {
      const { [clave]: _quitado, ...resto } = v
      return resto
    })
  }

  async function guardar() {
    setOcupado(true)
    setError(null)
    setAviso(null)
    try {
      const r = await backoffice.apariencia.guardar(limpio)
      setGuardado(r.tema)
      setValores(r.tema)
      setResultados(r.resultados)
      const mal = r.resultados.filter((x) => ETIQUETA[x.estado].mala).length
      setAviso(
        mal === 0
          ? 'Guardado y aplicado a todas las instancias que corren.'
          : `Guardado. ${mal} instancia${mal === 1 ? '' : 's'} no lo recibió: queda guardado y se puede reaplicar.`,
      )
      void leerEstado()
    } catch (err) {
      setError(describirError(err))
    } finally {
      setOcupado(false)
    }
  }

  async function reaplicar() {
    setOcupado(true)
    setError(null)
    try {
      const r = await backoffice.apariencia.aplicar()
      setResultados(r.resultados)
      setAviso('Se volvió a aplicar el tema guardado a todas las instancias.')
      void leerEstado()
    } catch (err) {
      setError(describirError(err))
    } finally {
      setOcupado(false)
    }
  }

  if (cargando) return <p className="text-sm text-muted-foreground">Cargando…</p>

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Apariencia de la suite</CardTitle>
          <CardDescription>
            Los colores se aplican a todas las instancias de este producto. Los que no cambies usan los de siempre. Un cambio se ve en el
            siguiente arranque de la pantalla de cada usuario.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          {COLORES_DE_TEMA.map((def) => {
            const personalizado = limpio[def.clave] !== undefined
            const valor = valores[def.clave] ?? def.porDefecto
            return (
              <div key={def.clave} className="grid gap-1.5">
                <div className="flex flex-wrap items-center gap-2">
                  <Label htmlFor={`hex-${def.clave}`}>{def.etiqueta}</Label>
                  <Badge variant={personalizado ? 'default' : 'outline'}>{personalizado ? 'Personalizado' : 'De siempre'}</Badge>
                </div>
                <p className="text-xs text-muted-foreground">{def.ayuda}</p>
                <div className="flex flex-wrap items-center gap-2">
                  <input
                    type="color"
                    aria-label={`Elegir ${def.etiqueta}`}
                    value={/^#[0-9a-f]{6}$/i.test(valor) ? valor : def.porDefecto}
                    onChange={(e) => poner(def.clave, e.target.value)}
                    className="h-9 w-12 cursor-pointer rounded border bg-transparent p-0.5"
                  />
                  <Input
                    id={`hex-${def.clave}`}
                    value={valor}
                    onChange={(e) => poner(def.clave, e.target.value)}
                    className="w-32 font-mono"
                    spellCheck={false}
                    aria-invalid={errores[def.clave] ? true : undefined}
                  />
                  {personalizado && (
                    <Button type="button" variant="ghost" size="sm" onClick={() => usarElDeSiempre(def.clave)}>
                      <RotateCcw />Usar el de siempre
                    </Button>
                  )}
                </div>
                {errores[def.clave] && (
                  <p role="alert" className="text-xs text-destructive">
                    {errores[def.clave]}
                  </p>
                )}
              </div>
            )
          })}

          <div className="grid gap-1.5">
            <p className="text-sm font-medium">Vista previa</p>
            <Vista fondo={color('menuActivoFondo')} borde={color('menuActivoBorde')} />
          </div>

          {error && (
            <p role="alert" className="text-sm font-medium text-destructive">
              {error}
            </p>
          )}
          {aviso && <p className="text-sm text-muted-foreground">{aviso}</p>}

          <div className="flex flex-wrap gap-2">
            <Button onClick={guardar} disabled={ocupado || hayErrores || (!cambios && resultados !== null)}>
              <Save />Guardar y aplicar a todas las instancias
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={ocupado || Object.keys(valores).length === 0}
              onClick={() => { setAviso(null); setValores({}) }}
            >
              <RotateCcw />Restaurar los valores de siempre
            </Button>
          </div>
          {Object.keys(valores).length === 0 && Object.keys(guardado).length > 0 && (
            <p className="text-xs text-muted-foreground">
              Se van a quitar todos los colores personalizados de las instancias cuando guardes.
            </p>
          )}
        </CardContent>
      </Card>

      {resultados && (
        <Card>
          <CardHeader>
            <CardTitle>Resultado</CardTitle>
            <CardDescription>Qué pasó con cada instancia al aplicar.</CardDescription>
          </CardHeader>
          <CardContent>
            {resultados.map((r) => <Estado key={r.slug} r={r} />)}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Estado de las instancias</CardTitle>
          <CardDescription>Si cada instancia tiene el tema guardado. Una instancia nueva o restaurada de un respaldo puede quedar atrás.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {estado === null && <p className="text-sm text-muted-foreground">No se pudo consultar el estado.</p>}
          {estado?.length === 0 && <p className="text-sm text-muted-foreground">No hay instancias.</p>}
          {estado?.map((r) => <Estado key={r.slug} r={r} />)}
          <div className="flex gap-2">
            <Button type="button" variant="outline" size="sm" onClick={() => void leerEstado()} disabled={ocupado}>
              <RefreshCw />Actualizar
            </Button>
            <Button type="button" variant="outline" size="sm" onClick={reaplicar} disabled={ocupado}>
              Reaplicar a todas
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
