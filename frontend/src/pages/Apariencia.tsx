// «Apariencia»: los colores de la suite. Se eligen acá y el backoffice los empuja a TODAS las instancias del producto (ADR-007 de
// `libra-ui`; cada instancia los guarda y los sirve ella misma, `libracore.tema_router`, ADR-012).
//
// La lista de colores NO está escrita acá: sale de `COLORES_DE_TEMA` de `libra-ui/tema`, la misma que lee la instancia y la SPA. Agregar un
// color al kit lo agrega a esta pantalla sin tocarla. Lo que sí hace la pantalla es no dejar mandar nada inválido (`validarTema`: un fondo
// sobre el que ningún texto se lee no pasa) y mostrar, antes de guardar, cómo queda.
import { useCallback, useEffect, useMemo, useState } from 'react'
import { RotateCcw, Save, RefreshCw } from 'lucide-react'
import { IDENTIDAD, TEXTO_SOBRE_ACENTO_OSCURO, defectosDelProducto, menuActivoDeProducto, type Producto } from 'libra-ui/identidad'
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

/** El producto de este backoffice (`PRODUCT_SLUG`) si es uno de la familia; si no (un backend viejo que no lo manda, un slug nuevo que el kit no
 *  conoce todavía), `null` y la pantalla dibuja los defectos neutros de `COLORES_DE_TEMA`. */
function productoConocido(slug: string | undefined): Producto | null {
  return slug && Object.prototype.hasOwnProperty.call(IDENTIDAD, slug) ? (slug as Producto) : null
}

type ColoresDeVista = Record<'menuActivoFondo' | 'menuActivoBorde' | 'acento' | 'barra' | 'exito' | 'posInicio' | 'posFin', string | undefined>

/** Cómo queda con los colores elegidos, en modo claro y en oscuro: la barra lateral con el ítem activo, un botón con el acento, un monto de
 *  éxito y la franja del POS. Los textos se calculan como en la app (`textoSobre`), así lo que se ve acá es lo que van a ver. Lo que no se
 *  eligió se dibuja con el de siempre DEL PRODUCTO (`defectosDelProducto` de `libra-ui/identidad`, ADR-036): el ítem activo, el botón y el acento
 *  del modo oscuro son los que la app pinta de verdad con `aplicarIdentidad`, no un verde ni un negro genéricos. Sin producto conocido, neutros. */
function Vista({ c, producto }: { c: ColoresDeVista; producto: Producto | null }) {
  const defectos = producto ? defectosDelProducto(producto) : null
  const defecto = (clave: (typeof COLORES_DE_TEMA)[number]['clave']) =>
    defectos?.[clave] ?? COLORES_DE_TEMA.find((d) => d.clave === clave)!.porDefecto
  const fondoItem = c.menuActivoFondo ?? defecto('menuActivoFondo')
  // Un fondo elegido calcula su texto (`aplicarTema`); el del producto trae el suyo, un tono de su color (`menuActivoDeProducto`).
  const textoItem = c.menuActivoFondo || !producto ? textoSobre(fondoItem) : menuActivoDeProducto(producto).texto
  const bordeItem = c.menuActivoBorde ?? defecto('menuActivoBorde')
  const posInicio = c.posInicio ?? '#0284c7'
  const posFin = c.posFin ?? '#4f46e5'
  const exito = c.exito ?? '#059669'
  const item = (activo: boolean, nombre: string, texto: string) => (
    <div
      className="rounded-md px-3 py-2 text-sm"
      style={activo ? { backgroundColor: fondoItem, color: textoItem, boxShadow: `inset 3px 0 0 ${bordeItem}` } : { color: texto }}
    >
      {nombre}
    </div>
  )
  const panel = (oscuro: boolean) => {
    const barra = c.barra ?? (oscuro ? '#171717' : defecto('barraLateralFondo'))
    const textoBarra = c.barra ? textoSobre(c.barra) : oscuro ? '#fafafa' : '#262626'
    // El acento del producto cambia con el modo (`colorAccion` en claro, `colorSobreOscuro` en oscuro, con el texto que fija `aplicarIdentidad`);
    // uno elegido vale igual en los dos y su texto se calcula.
    const acento = c.acento ?? (producto ? (oscuro ? IDENTIDAD[producto].colorSobreOscuro : defecto('acento')) : oscuro ? '#e5e5e5' : '#171717')
    const textoAcento = c.acento || !producto ? textoSobre(acento) : oscuro ? TEXTO_SOBRE_ACENTO_OSCURO : '#ffffff'
    return (
      <div className={`overflow-hidden rounded-lg border ${oscuro ? 'bg-neutral-950 text-neutral-100' : 'bg-white text-neutral-800'}`}>
        <div className="flex">
          <div className="w-1/2 space-y-1 p-3" style={{ backgroundColor: barra }}>
            {item(false, 'Ventas', textoBarra)}
            {item(true, 'Ítem activo', textoBarra)}
            {item(false, 'Clientes', textoBarra)}
          </div>
          <div className="flex w-1/2 flex-col items-start justify-center gap-2 p-3 text-sm">
            <span className="rounded-md px-3 py-1.5 font-medium" style={{ backgroundColor: acento, color: textoAcento }}>Guardar</span>
            <span className="font-semibold" style={{ color: exito }}>+ $ 12.500</span>
          </div>
        </div>
        <div className="px-3 py-2 text-sm font-semibold" style={{ backgroundImage: `linear-gradient(to right, ${posInicio}, ${posFin})`, color: c.posInicio ? textoSobre(posInicio) : '#ffffff' }}>
          POS (Caja) · Nueva venta
        </div>
      </div>
    )
  }
  return (
    <div className="grid gap-3 sm:grid-cols-2" aria-label="Vista previa">
      {panel(false)}
      {panel(true)}
    </div>
  )
}

export function Apariencia() {
  const [guardado, setGuardado] = useState<Tema>({})
  const [producto, setProducto] = useState<Producto | null>(null)
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
      .then(({ tema, producto: slug }) => {
        setProducto(productoConocido(slug))
        setGuardado(tema)
        setValores(tema)
      })
      .catch((err) => setError(describirError(err)))
      .finally(() => setCargando(false))
    void leerEstado()
  }, [leerEstado])

  const { tema: limpio, errores } = useMemo(() => validarTema(valores), [valores])
  const defectos = useMemo(() => (producto ? defectosDelProducto(producto) : null), [producto])
  const hayErrores = Object.keys(errores).length > 0
  const cambios = JSON.stringify(limpio) !== JSON.stringify(guardado)

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
            Los colores se aplican a todas las instancias de este producto. Los que no cambies usan los de siempre{producto ? ` de ${IDENTIDAD[producto].nombre}` : ''}.
            Un cambio se ve en el siguiente arranque de la pantalla de cada usuario.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          {COLORES_DE_TEMA.map((def) => {
            const personalizado = limpio[def.clave] !== undefined
            // Con el producto conocido el «de siempre» es el SUYO (acento, barra, ítem activo); sin él, los que dependen del producto no tienen un
            // valor único y el campo queda vacío.
            const defecto = defectos ? defectos[def.clave] : def.defectoPorProducto ? '' : def.porDefecto
            const valor = valores[def.clave] ?? defecto
            return (
              <div key={def.clave} className="grid gap-1.5">
                <div className="flex flex-wrap items-center gap-2">
                  <Label htmlFor={`hex-${def.clave}`}>{def.etiqueta}</Label>
                  <Badge variant={personalizado ? 'default' : 'outline'}>{personalizado ? 'Personalizado' : def.defectoPorProducto && !defectos ? 'El de cada producto' : 'De siempre'}</Badge>
                </div>
                <p className="text-xs text-muted-foreground">{def.ayuda}</p>
                <div className="flex flex-wrap items-center gap-2">
                  <input
                    type="color"
                    aria-label={`Elegir ${def.etiqueta}`}
                    value={/^#[0-9a-f]{6}$/i.test(valor) ? valor : (defecto || def.porDefecto)}
                    onChange={(e) => poner(def.clave, e.target.value)}
                    className="h-9 w-12 cursor-pointer rounded border bg-transparent p-0.5"
                  />
                  <Input
                    id={`hex-${def.clave}`}
                    value={valor}
                    placeholder={def.defectoPorProducto ? 'del producto' : undefined}
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
            <Vista
              producto={producto}
              c={{
                menuActivoFondo: limpio.menuActivoFondo,
                menuActivoBorde: limpio.menuActivoBorde,
                acento: limpio.acento,
                barra: limpio.barraLateralFondo,
                exito: limpio.exito,
                posInicio: limpio.posEncabezadoInicio,
                posFin: limpio.posEncabezadoFin,
              }}
            />
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
