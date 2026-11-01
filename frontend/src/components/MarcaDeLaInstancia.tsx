// La pestaña «Marca»: el nombre, el logo, el color y los Términos propios con los que un revendedor vende esta instancia como suya (feature `marca`;
// `libracore.marca_router` ADR-092 y `libracore.terminos_propios` ADR-093; el diseño completo, en el wiki: `marca-blanca-piloto-diseno`).
//
// 🔴 **El orden de la pantalla es el orden que importa: primero los términos, después la marca.** Con marca propia la instancia TIENE que tener
// Términos propios (libraauth ADR-030); si no, queda frenada y sus usuarios no pueden entrar. Por eso el paso 1 son los términos, el backoffice
// rechaza guardar la marca antes (`409 terminos_primero`) y la única forma de seguir igual es tildar, a sabiendas, que la instancia queda frenada.
//
// El texto de los términos no se puede releer: la instancia guarda y devuelve sólo versión, vigencia y huella. Para cambiarlos se carga un texto
// nuevo con otra versión (una versión es un texto). La instancia es la que valida todo (40 caracteres de nombre, `#rrggbb`, 1 MB y PNG/JPG/WEBP
// de logo...): su 422 llega acá tal cual y se muestra donde se escribió.
import { useCallback, useEffect, useRef, useState } from 'react'
import { AlertTriangle, ImageUp, Save, Trash2 } from 'lucide-react'
import { acentoLegibleDeMarca, normalizarHex } from 'libra-ui/tema'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

import {
  ApiError, CODIGO_QUEDARIA_FRENADA, CODIGO_TERMINOS_PRIMERO, api, rutaMarca, type EstadoDeMarca,
} from '../api'
import { ConfirmDialog } from './confirm-dialog'

const COLOR = /^#[0-9a-fA-F]{6}$/

function describirError(err: unknown): string {
  return err instanceof ApiError ? err.detail : 'Error de conexión.'
}

/** El `detail.code` que mandó el backoffice (`terminos_primero`, `quedaria_frenada`), o `null`. */
function codigoDe(err: unknown): string | null {
  if (!(err instanceof ApiError)) return null
  const datos = err.detailData as { code?: unknown } | undefined
  return typeof datos?.code === 'string' ? datos.code : null
}

/** Cómo se vería el nombre con el logo y el color, tal cual lo va a dibujar la instancia (logo o inicial del nombre, sobre el color de acento). */
function VistaPrevia({ nombre, color, logo }: { nombre: string; color: string; logo: string | null }) {
  const valido = COLOR.test(color) ? color : undefined
  return (
    <div className="flex items-center gap-3 rounded-md border p-3" aria-label="Vista previa de la marca">
      {logo ? (
        <img src={logo} alt="" className="h-10 w-10 max-w-none object-contain" />
      ) : (
        <div
          className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary font-semibold text-primary-foreground"
          style={valido ? { backgroundColor: valido, color: '#ffffff' } : undefined}
        >
          {([...nombre.trim()][0] ?? '·').toUpperCase()}
        </div>
      )}
      <span className="font-semibold">{nombre.trim() || 'Sin nombre'}</span>
    </div>
  )
}

export function MarcaDeLaInstancia({ slug }: { slug: string }) {
  const base = rutaMarca(slug)
  const [estado, setEstado] = useState<EstadoDeMarca | null>(null)
  const [cargando, setCargando] = useState(true)
  const [sinSoporte, setSinSoporte] = useState<string | null>(null)
  const [ocupado, setOcupado] = useState(false)
  const [aviso, setAviso] = useState<string | null>(null)
  // Errores donde se originaron: así el de los términos no aparece debajo del botón de la marca.
  const [errorTerminos, setErrorTerminos] = useState<string | null>(null)
  const [errorMarca, setErrorMarca] = useState<string | null>(null)
  const [errorLogo, setErrorLogo] = useState<string | null>(null)

  // Términos
  const [version, setVersion] = useState('')
  const [vigenteDesde, setVigenteDesde] = useState('')
  const [texto, setTexto] = useState('')
  // Marca
  const [nombre, setNombre] = useState('')
  const [nombreCorto, setNombreCorto] = useState('')
  const [color, setColor] = useState('')
  // «Guardar igual aunque la instancia quede frenada»: sólo aparece después de que el backoffice rechazó por falta de términos.
  const [ofrecerSeguirSinTerminos, setOfrecerSeguirSinTerminos] = useState(false)
  const [seguirSinTerminos, setSeguirSinTerminos] = useState(false)

  const [confirmarVolver, setConfirmarVolver] = useState(false)
  const [confirmarQuitarTerminos, setConfirmarQuitarTerminos] = useState(false)
  const archivoLogo = useRef<HTMLInputElement>(null)

  const releer = useCallback(async () => {
    try {
      const e = await api.get<EstadoDeMarca>(base)
      setEstado(e)
      setSinSoporte(null)
      setNombre(e.marca.nombre)
      setNombreCorto(e.marca.nombre_corto)
      setColor(e.marca.color)
    } catch (err) {
      // 409 = una instancia vieja (libracore sin las rutas de la marca): se dice una vez, arriba, y no se dibuja un formulario que no puede andar.
      if (err instanceof ApiError && err.status === 409) setSinSoporte(err.detail)
      else setErrorMarca(describirError(err))
    } finally {
      setCargando(false)
    }
  }, [base])

  useEffect(() => { void releer() }, [releer])

  async function ejecutar(accion: () => Promise<unknown>, alFallar: (err: unknown) => void, mensaje: string) {
    setOcupado(true)
    setAviso(null)
    setErrorTerminos(null)
    setErrorMarca(null)
    setErrorLogo(null)
    try {
      await accion()
      setAviso(mensaje)
      await releer()
    } catch (err) {
      alFallar(err)
    } finally {
      setOcupado(false)
    }
  }

  const guardarTerminos = () =>
    ejecutar(
      async () => {
        await api.put(`${base}/terminos`, { version: version.trim(), vigente_desde: vigenteDesde.trim(), texto })
        setTexto('')
      },
      (err) => setErrorTerminos(describirError(err)),
      'Términos guardados.',
    )

  const quitarTerminos = (confirmar: boolean) =>
    ejecutar(
      () => api.del(`${base}/terminos${confirmar ? '?confirmar=true' : ''}`),
      (err) => {
        // Quitarlos dejaría frenada a una instancia con marca propia: se pide confirmar, y se hace sólo si se confirma.
        if (codigoDe(err) === CODIGO_QUEDARIA_FRENADA) setConfirmarQuitarTerminos(true)
        else setErrorTerminos(describirError(err))
      },
      'Términos quitados.',
    )

  const guardarMarca = () =>
    ejecutar(
      async () => {
        await api.put(base, {
          nombre: nombre.trim(), nombre_corto: nombreCorto.trim(), color: color.trim(), sin_terminos: seguirSinTerminos,
        })
        setOfrecerSeguirSinTerminos(false)
        setSeguirSinTerminos(false)
      },
      (err) => {
        if (codigoDe(err) === CODIGO_TERMINOS_PRIMERO) setOfrecerSeguirSinTerminos(true)
        setErrorMarca(describirError(err))
      },
      'Marca guardada.',
    )

  const subirLogo = (archivo: File) =>
    ejecutar(
      async () => {
        const form = new FormData()
        form.append('logo', archivo)
        await api.postForm(`${base}/logo${seguirSinTerminos ? '?sin_terminos=true' : ''}`, form)
      },
      (err) => {
        if (codigoDe(err) === CODIGO_TERMINOS_PRIMERO) setOfrecerSeguirSinTerminos(true)
        setErrorLogo(describirError(err))
      },
      'Logo guardado.',
    ).finally(() => {
      if (archivoLogo.current) archivoLogo.current.value = ''
    })

  const quitarLogo = () => ejecutar(() => api.del(`${base}/logo`), (err) => setErrorLogo(describirError(err)), 'Logo quitado.')

  const volverALaMarcaDelProducto = () =>
    ejecutar(() => api.del(base), (err) => setErrorMarca(describirError(err)), 'La instancia vuelve a la marca de su producto.')

  async function cargarArchivoDeTerminos(archivo: File | undefined) {
    if (!archivo) return
    setTexto(await archivo.text())
  }

  if (cargando) return <p className="text-sm text-muted-foreground">Cargando…</p>

  if (sinSoporte || !estado) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Esta instancia todavía no tiene la marca</CardTitle>
          <CardDescription>{sinSoporte ?? 'No se pudo leer la marca de la instancia.'}</CardDescription>
        </CardHeader>
        {errorMarca && <CardContent><p className="text-sm font-medium text-destructive">{errorMarca}</p></CardContent>}
      </Card>
    )
  }

  const { marca, terminos } = estado
  const frenada = marca.propia && !terminos.cargados
  // La vista previa sale por este backoffice (la instancia no está en internet). La versión es el hash de la ruta que contesta la instancia
  // (`/api/marca/logo?v=<hash>`): cambia cuando cambia el logo, así el navegador no muestra el anterior.
  const versionDelLogo = marca.logo ? new URLSearchParams(marca.logo.split('?')[1] ?? '').get('v') : null
  const logoVisible = marca.logo ? `${base}/logo${versionDelLogo ? `?v=${encodeURIComponent(versionDelLogo)}` : ''}` : null
  const colorInvalido = color.trim() !== '' && !COLOR.test(color.trim())
  // Lo que la instancia va a dibujar de verdad: el kit corrige el color que no se distingue del fondo en claro y en oscuro (ADR-102) o lo
  // descarta si habría que cambiarlo demasiado. Se calcula con la misma función, así el aviso y la vista previa no se pueden separar.
  const colorElegido = COLOR.test(color.trim()) ? normalizarHex(color) : null
  const colorAplicado = colorElegido ? acentoLegibleDeMarca(colorElegido) : undefined
  const colorDescartado = colorElegido !== null && colorAplicado === undefined
  const colorCorregido = colorElegido !== null && colorAplicado !== undefined && colorAplicado !== colorElegido

  return (
    <div className="space-y-6">
      {aviso && <p className="text-sm font-medium text-primary" role="status">{aviso}</p>}

      <Card>
        <CardHeader>
          <CardTitle>Marca de la instancia</CardTitle>
          <CardDescription>
            Con marca propia esta instancia se ve y se vende con otro nombre, otro logo y otros términos: no aparece nada de la marca del producto. Es
            de <strong>esta</strong> instancia; no se empuja a las demás, y «Apariencia» ya no le cambia los colores.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-2">
          <Badge variant={marca.propia ? 'default' : 'outline'}>{marca.propia ? 'Marca propia' : 'Marca del producto'}</Badge>
          <Badge variant={terminos.cargados ? 'default' : 'outline'}>
            {terminos.cargados ? `Términos propios: versión ${terminos.version}` : 'Términos propios: sin cargar'}
          </Badge>
        </CardContent>
      </Card>

      {frenada && (
        <Card className="border-destructive" role="alert">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-destructive">
              <AlertTriangle className="h-4 w-4" /> Los usuarios de esta instancia no pueden entrar
            </CardTitle>
            <CardDescription>
              Tiene marca propia y no tiene Términos propios cargados, así que ve una pantalla que le avisa que su cuenta todavía no los tiene. Cargá los
              términos en el paso 1.
            </CardDescription>
          </CardHeader>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>1. Términos y Condiciones del revendedor</CardTitle>
          <CardDescription>
            El contrato que aceptan los usuarios de esta instancia, en lugar del de la familia. Se carga primero. <strong>No se puede volver a leer</strong>{' '}
            desde acá: se guarda su huella. Para cambiarlo, cargá el texto nuevo con otro número de versión.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {terminos.cargados && (
            <p className="text-sm text-muted-foreground" data-testid="terminos-cargados">
              Cargados: versión <strong>{terminos.version}</strong>, vigente desde {terminos.vigente_desde}, {terminos.caracteres.toLocaleString('es-AR')} caracteres.
              Huella <code>{terminos.hash.slice(0, 12)}</code>…
            </p>
          )}
          <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); void guardarTerminos() }}>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="grid gap-2">
                <Label htmlFor="terminos-version">Versión</Label>
                <Input id="terminos-version" value={version} maxLength={20} placeholder="2026-1" onChange={(e) => setVersion(e.target.value)} />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="terminos-vigente">Vigente desde</Label>
                <Input id="terminos-vigente" value={vigenteDesde} maxLength={10} placeholder="dd-mm-aaaa" onChange={(e) => setVigenteDesde(e.target.value)} />
              </div>
            </div>
            <div className="grid gap-2">
              <Label htmlFor="terminos-texto">Texto (Markdown)</Label>
              <textarea
                id="terminos-texto"
                value={texto}
                onChange={(e) => setTexto(e.target.value)}
                rows={12}
                className="w-full rounded-md border border-input bg-transparent px-3 py-2 font-mono text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
              <div className="flex flex-wrap items-center gap-3">
                <Label htmlFor="terminos-archivo" className="text-xs font-normal text-muted-foreground">O cargar un archivo .md o .txt</Label>
                <input
                  id="terminos-archivo" type="file" accept=".md,.txt,text/markdown,text/plain" className="text-xs"
                  onChange={(e) => void cargarArchivoDeTerminos(e.target.files?.[0])}
                />
              </div>
            </div>
            {errorTerminos && <p className="text-sm font-medium text-destructive">{errorTerminos}</p>}
            <div className="flex flex-wrap gap-2">
              <Button type="submit" disabled={ocupado || !version.trim() || !vigenteDesde.trim() || !texto.trim()}>
                <Save className="mr-1 h-4 w-4" /> Guardar términos
              </Button>
              {terminos.cargados && (
                <Button type="button" variant="outline" disabled={ocupado} onClick={() => void quitarTerminos(false)}>
                  <Trash2 className="mr-1 h-4 w-4" /> Quitar los términos
                </Button>
              )}
            </div>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>2. Nombre, color y logo</CardTitle>
          <CardDescription>
            Reemplazan al nombre, al ícono y a los colores del producto en el ingreso, el menú, la recuperación de contraseña, el título de la pestaña y la
            aplicación instalable.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <VistaPrevia nombre={nombre} color={colorElegido === null ? color : (colorAplicado ?? '')} logo={logoVisible} />

          <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); void guardarMarca() }}>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="grid gap-2">
                <Label htmlFor="marca-nombre">Nombre</Label>
                <Input id="marca-nombre" value={nombre} maxLength={40} placeholder="Gestión Sur" onChange={(e) => setNombre(e.target.value)} />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="marca-corto">Nombre corto (aplicación instalable)</Label>
                <Input id="marca-corto" value={nombreCorto} maxLength={12} placeholder="GSur" onChange={(e) => setNombreCorto(e.target.value)} />
              </div>
            </div>
            <div className="grid gap-2">
              <Label htmlFor="marca-color">Color de la marca</Label>
              <div className="flex items-center gap-2 sm:max-w-xs">
                <input
                  type="color" aria-label="Elegir color" value={COLOR.test(color.trim()) ? color.trim() : '#336699'}
                  onChange={(e) => setColor(e.target.value)} className="h-9 w-12 cursor-pointer rounded border"
                />
                <Input id="marca-color" value={color} maxLength={7} placeholder="#336699" aria-invalid={colorInvalido} onChange={(e) => setColor(e.target.value)} />
              </div>
              {colorInvalido && <p className="text-xs text-destructive">Se espera #rrggbb.</p>}
              {colorCorregido && (
                <p className="max-w-prose text-xs text-amber-700 dark:text-amber-400" role="status">
                  Este color no se distingue bien del fondo en modo claro y oscuro: la instancia va a usar <strong>{colorAplicado}</strong>, el tono
                  más parecido que sí se lee. Elegí otro si querés exactamente el que escribiste.
                </p>
              )}
              {colorDescartado && (
                <p className="max-w-prose text-xs text-amber-700 dark:text-amber-400" role="status">
                  Este color se confunde con el fondo (casi blanco o casi negro) y no se puede corregir sin cambiarlo demasiado: la instancia{' '}
                  <strong>no lo va a usar</strong> y los botones quedan con el color del producto. Elegí uno más intenso.
                </p>
              )}
            </div>

            {errorMarca && <p className="text-sm font-medium text-destructive">{errorMarca}</p>}
            {ofrecerSeguirSinTerminos && (
              <label className="flex items-start gap-2 text-sm">
                <input type="checkbox" checked={seguirSinTerminos} onChange={(e) => setSeguirSinTerminos(e.target.checked)} className="mt-1" />
                <span>
                  Guardar igual: entiendo que los usuarios de esta instancia <strong>no van a poder entrar</strong> hasta que se carguen sus Términos.
                </span>
              </label>
            )}
            <Button type="submit" disabled={ocupado || colorInvalido || (!nombre.trim() && !color.trim() && !marca.propia)}>
              <Save className="mr-1 h-4 w-4" /> Guardar marca
            </Button>
          </form>

          <div className="space-y-3 border-t pt-4">
            <p className="text-sm font-medium">Logo</p>
            <p className="text-xs text-muted-foreground">PNG, JPG o WEBP, de 192 px de lado o más y hasta 1 MB. No se aceptan SVG.</p>
            <div className="flex flex-wrap items-center gap-3">
              <input
                ref={archivoLogo} type="file" accept="image/png,image/jpeg,image/webp" aria-label="Elegir logo" className="text-xs" disabled={ocupado}
                onChange={(e) => { const f = e.target.files?.[0]; if (f) void subirLogo(f) }}
              />
              {marca.logo && (
                <Button type="button" variant="outline" size="sm" disabled={ocupado} onClick={() => void quitarLogo()}>
                  <ImageUp className="mr-1 h-4 w-4" /> Quitar logo
                </Button>
              )}
            </div>
            {errorLogo && <p className="text-sm font-medium text-destructive">{errorLogo}</p>}
          </div>
        </CardContent>
      </Card>

      {(marca.propia || terminos.cargados) && (
        <Card className="border-destructive/50">
          <CardHeader>
            <CardTitle>Volver a la marca del producto</CardTitle>
            <CardDescription>
              Borra el nombre, el logo y el color <strong>y también los Términos propios</strong>: la instancia vuelve a verse y a regirse como las demás
              del producto. Los usuarios tendrán que aceptar los términos de la familia si todavía no lo hicieron.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button type="button" variant="destructive" disabled={ocupado} onClick={() => setConfirmarVolver(true)}>
              Volver a la marca del producto
            </Button>
          </CardContent>
        </Card>
      )}

      <ConfirmDialog
        open={confirmarVolver} onOpenChange={setConfirmarVolver}
        title="¿Volver a la marca del producto?"
        description="Se borran el nombre, el logo, el color y los Términos propios de esta instancia."
        confirmLabel="Volver a la marca del producto"
        onConfirm={() => void volverALaMarcaDelProducto()}
      />
      <ConfirmDialog
        open={confirmarQuitarTerminos} onOpenChange={setConfirmarQuitarTerminos}
        title="¿Quitar los Términos igual?"
        description="Esta instancia tiene marca propia: sin sus Términos queda frenada y sus usuarios no pueden entrar hasta que se carguen otros."
        confirmLabel="Quitarlos igual"
        onConfirm={() => void quitarTerminos(true)}
      />
    </div>
  )
}
