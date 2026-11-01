// La consola de revendedores (feature `revendedores`): quiénes son, qué productos pueden vender, qué instancias son suyas y el
// bloqueo. La marca, los planes y el alta de instancias siguen en el backoffice de cada producto: acá no se duplican. Diseño en el
// wiki: `consola-de-revendedores-diseno`.
//
// 🔴 Desbloquear reactiva sólo lo que suspendió la consola: una instancia que ya estaba suspendida (falta de pago, por ejemplo) no
// vuelve. La pantalla lo dice en las dos puntas, porque es lo primero que alguien asumiría al revés.
import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import { AlertTriangle, ArrowLeft, Ban, Plus, RotateCcw, Save, Trash2 } from 'lucide-react'
import { SelectBuscable } from 'libra-ui/SelectBuscable'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

import {
  ApiError, backoffice, type ProductoDelCatalogo, type Revendedor as TRevendedor, type ResultadoDeBloqueo,
} from '../api'

function describirError(err: unknown): string {
  if (err instanceof ApiError) return err.detail
  return 'Error de conexión.'
}

function EstadoDelRevendedor({ estado }: { estado: TRevendedor['estado'] }) {
  return <Badge variant={estado === 'activo' ? 'default' : 'destructive'}>{estado === 'activo' ? 'Activo' : 'Bloqueado'}</Badge>
}

function Productos({
  catalogo, elegidos, onChange,
}: { catalogo: ProductoDelCatalogo[]; elegidos: string[]; onChange: (productos: string[]) => void }) {
  return (
    <fieldset className="grid gap-2">
      <legend className="text-sm font-medium">Productos que puede vender</legend>
      <div className="flex flex-wrap gap-x-4 gap-y-2">
        {catalogo.map((p) => (
          <label key={p.slug} className="flex items-center gap-2 text-sm">
            <input
              type="checkbox" checked={elegidos.includes(p.slug)}
              onChange={(e) => onChange(e.target.checked ? [...elegidos, p.slug] : elegidos.filter((s) => s !== p.slug))}
            />
            {p.nombre}
          </label>
        ))}
      </div>
    </fieldset>
  )
}

export function Revendedores() {
  const [revendedores, setRevendedores] = useState<TRevendedor[] | null>(null)
  const [catalogo, setCatalogo] = useState<ProductoDelCatalogo[]>([])
  const [error, setError] = useState('')
  const [nombre, setNombre] = useState('')
  const [contacto, setContacto] = useState('')
  const [productos, setProductos] = useState<string[]>([])
  const [ocupado, setOcupado] = useState(false)

  const cargar = useCallback(async () => {
    try {
      const [lista, cat] = await Promise.all([backoffice.revendedores.listar(), backoffice.revendedores.catalogo()])
      setRevendedores(lista.revendedores)
      setCatalogo(cat.productos)
    } catch (err) {
      setError(describirError(err))
    }
  }, [])

  useEffect(() => { void cargar() }, [cargar])

  async function crear(e: FormEvent) {
    e.preventDefault()
    setOcupado(true)
    setError('')
    try {
      await backoffice.revendedores.crear({ nombre: nombre.trim(), contacto: contacto.trim(), notas: '', productos })
      setNombre('')
      setContacto('')
      setProductos([])
      await cargar()
    } catch (err) {
      setError(describirError(err))
    } finally {
      setOcupado(false)
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Revendedores</h1>
        <p className="text-sm text-muted-foreground">Quién vende la suite con su marca, qué puede vender y qué instancias son suyas.</p>
      </div>
      {error && <p className="text-sm font-medium text-destructive" role="alert">{error}</p>}

      <Card>
        <CardHeader><CardTitle>Revendedores cargados</CardTitle></CardHeader>
        <CardContent>
          {revendedores === null && !error && <p className="text-sm text-muted-foreground">Cargando…</p>}
          {revendedores?.length === 0 && <p className="text-sm text-muted-foreground">Todavía no hay ningún revendedor.</p>}
          {revendedores?.map((r) => (
            <div key={r.id} className="flex flex-wrap items-center justify-between gap-2 border-b py-2 last:border-0">
              <div className="min-w-0">
                <Link to={`/revendedores/${r.id}`} className="truncate text-sm font-medium underline-offset-4 hover:underline">{r.nombre}</Link>
                <p className="truncate text-xs text-muted-foreground">
                  {r.instancias.length} {r.instancias.length === 1 ? 'instancia' : 'instancias'}
                  {r.contacto && ` · ${r.contacto}`}
                </p>
              </div>
              <EstadoDelRevendedor estado={r.estado} />
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Nuevo revendedor</CardTitle></CardHeader>
        <CardContent>
          <form onSubmit={crear} className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="grid gap-2">
                <Label htmlFor="rev-nombre">Nombre</Label>
                <Input id="rev-nombre" value={nombre} maxLength={120} required onChange={(e) => setNombre(e.target.value)} />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="rev-contacto">Contacto</Label>
                <Input id="rev-contacto" value={contacto} maxLength={200} onChange={(e) => setContacto(e.target.value)} />
              </div>
            </div>
            <Productos catalogo={catalogo} elegidos={productos} onChange={setProductos} />
            <Button type="submit" disabled={ocupado || !nombre.trim()}><Plus className="h-4 w-4" />Agregar revendedor</Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}

const RESULTADO: Record<ResultadoDeBloqueo['resultado'], string> = {
  suspendida: 'Suspendida',
  ya_estaba_suspendida: 'Ya estaba suspendida: al desbloquear no vuelve',
  activada: 'Reactivada',
  sin_cambios: 'Sin cambios: no la suspendió la consola',
  fallo: 'No se pudo',
}

export function Revendedor() {
  const { id = '' } = useParams()
  const [revendedor, setRevendedor] = useState<TRevendedor | null>(null)
  const [catalogo, setCatalogo] = useState<ProductoDelCatalogo[]>([])
  const [error, setError] = useState('')
  const [ocupado, setOcupado] = useState(false)
  const [nombre, setNombre] = useState('')
  const [contacto, setContacto] = useState('')
  const [notas, setNotas] = useState('')
  const [productos, setProductos] = useState<string[]>([])
  const [paraAsignar, setParaAsignar] = useState('')
  const [bloqueando, setBloqueando] = useState(false)
  const [confirmar, setConfirmar] = useState('')
  const [mensaje, setMensaje] = useState('')
  const [resultados, setResultados] = useState<ResultadoDeBloqueo[] | null>(null)

  const mostrar = useCallback((r: TRevendedor) => {
    setRevendedor(r)
    setNombre(r.nombre)
    setContacto(r.contacto)
    setNotas(r.notas)
    setProductos(r.productos)
  }, [])

  const cargarCatalogo = useCallback(async () => {
    setCatalogo((await backoffice.revendedores.catalogo()).productos)
  }, [])

  useEffect(() => {
    void (async () => {
      try {
        mostrar(await backoffice.revendedores.detalle(id))
        await cargarCatalogo()
      } catch (err) {
        setError(describirError(err))
      }
    })()
  }, [id, mostrar, cargarCatalogo])

  // Sólo instancias de lo que tiene habilitado y sin dueño: lo demás el backend igual lo rechazaría.
  const disponibles = useMemo(() => catalogo
    .filter((p) => revendedor?.productos.includes(p.slug))
    .flatMap((p) => p.instancias.filter((i) => !i.revendedor).map((i) => ({ producto: p.slug, nombreProducto: p.nombre, ...i }))),
  [catalogo, revendedor])
  const caidos = catalogo.filter((p) => !p.alcanzable)

  async function hacer(paso: () => Promise<void>) {
    setOcupado(true)
    setError('')
    try {
      await paso()
    } catch (err) {
      setError(describirError(err))
    } finally {
      setOcupado(false)
    }
  }

  if (!revendedor) {
    return error
      ? <p className="text-sm font-medium text-destructive" role="alert">{error}</p>
      : <p className="text-sm text-muted-foreground">Cargando…</p>
  }

  const bloqueado = revendedor.estado === 'bloqueado'
  const seguir = () => hacer(async () => {
    const r = await backoffice.revendedores.bloquear(id, confirmar, mensaje.trim())
    mostrar(r.revendedor)
    setResultados(r.resultados)
    setBloqueando(false)
    setConfirmar('')
    await cargarCatalogo()
  })

  return (
    <div className="space-y-6">
      <Link to="/revendedores" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:underline">
        <ArrowLeft className="h-4 w-4" />Revendedores
      </Link>
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold">{revendedor.nombre}</h1>
        <EstadoDelRevendedor estado={revendedor.estado} />
      </div>
      {error && <p className="text-sm font-medium text-destructive" role="alert">{error}</p>}
      {caidos.map((p) => (
        <p key={p.slug} className="flex items-center gap-2 text-sm text-destructive">
          <AlertTriangle className="h-4 w-4" />El backoffice de {p.nombre}: {p.detalle}.
        </p>
      ))}

      {resultados && (
        <Card>
          <CardHeader><CardTitle>Resultado</CardTitle></CardHeader>
          <CardContent>
            {resultados.length === 0 && <p className="text-sm text-muted-foreground">No tiene instancias.</p>}
            {resultados.map((f) => (
              <div key={`${f.producto}/${f.slug}`} className="flex flex-wrap justify-between gap-2 border-b py-2 text-sm last:border-0">
                <span>{f.producto} / {f.slug}</span>
                <span className={f.resultado === 'fallo' ? 'font-medium text-destructive' : 'text-muted-foreground'}>
                  {RESULTADO[f.resultado]}{f.detalle && `: ${f.detalle}`}
                </span>
              </div>
            ))}
            {resultados.some((f) => f.resultado === 'fallo') && (
              <p className="mt-3 text-sm">Hubo errores. Repetir la acción sigue desde donde quedó.</p>
            )}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader><CardTitle>Datos y productos</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="grid gap-2">
              <Label htmlFor="rev-nombre">Nombre</Label>
              <Input id="rev-nombre" value={nombre} maxLength={120} onChange={(e) => setNombre(e.target.value)} />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="rev-contacto">Contacto</Label>
              <Input id="rev-contacto" value={contacto} maxLength={200} onChange={(e) => setContacto(e.target.value)} />
            </div>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="rev-notas">Notas</Label>
            <textarea
              id="rev-notas" value={notas} maxLength={2000} rows={3} onChange={(e) => setNotas(e.target.value)}
              className="rounded-md border bg-transparent px-3 py-2 text-sm"
            />
          </div>
          <Productos catalogo={catalogo} elegidos={productos} onChange={setProductos} />
          <Button
            disabled={ocupado || !nombre.trim()}
            onClick={() => hacer(async () => mostrar(await backoffice.revendedores.editar(id, {
              nombre: nombre.trim(), contacto: contacto.trim(), notas, productos,
            })))}
          >
            <Save className="h-4 w-4" />Guardar
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Instancias</CardTitle>
          <CardDescription>La marca, el plan y los adicionales de cada una se manejan en el backoffice de su producto.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {revendedor.instancias.length === 0 && <p className="text-sm text-muted-foreground">Todavía no tiene instancias.</p>}
          {revendedor.instancias.map((i) => {
            const suspendida = revendedor.suspendidas.some((s) => s.producto === i.producto && s.slug === i.slug)
            return (
              <div key={`${i.producto}/${i.slug}`} className="flex flex-wrap items-center justify-between gap-2 border-b py-2 last:border-0">
                <span className="text-sm">{i.producto} / {i.slug}</span>
                <span className="flex items-center gap-2">
                  {suspendida && <Badge variant="destructive">Suspendida por la consola</Badge>}
                  <Button
                    variant="outline" size="sm" disabled={ocupado || suspendida} aria-label={`Quitar ${i.producto} ${i.slug}`}
                    onClick={() => hacer(async () => {
                      mostrar(await backoffice.revendedores.quitar(id, i))
                      await cargarCatalogo()
                    })}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </span>
              </div>
            )
          })}
          {!bloqueado && (
            <div className="flex flex-wrap items-end gap-2">
              <div className="grid min-w-64 flex-1 gap-2">
                <Label htmlFor="rev-instancia">Asignar instancia</Label>
                <SelectBuscable
                  id="rev-instancia" ariaLabel="Asignar instancia" value={paraAsignar} onChange={setParaAsignar}
                  placeholder="Elegir…" emptyMessage="No hay instancias libres de sus productos."
                  opciones={disponibles.map((d) => ({
                    value: `${d.producto}/${d.slug}`, label: `${d.nombreProducto}: ${d.nombre || d.slug}`,
                  }))}
                />
              </div>
              <Button
                variant="outline" disabled={ocupado || !paraAsignar}
                onClick={() => hacer(async () => {
                  const [producto, ...slug] = paraAsignar.split('/')
                  mostrar(await backoffice.revendedores.asignar(id, { producto, slug: slug.join('/') }))
                  setParaAsignar('')
                  await cargarCatalogo()
                })}
              >
                <Plus className="h-4 w-4" />Asignar
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      <Card className="border-destructive/50">
        <CardHeader>
          <CardTitle>{bloqueado ? 'Desbloquear' : 'Bloquear'}</CardTitle>
          <CardDescription>
            {bloqueado
              ? 'Reactiva sólo las instancias que suspendió la consola. Las que ya estaban suspendidas, por falta de pago por ejemplo, siguen como estaban.'
              : 'Suspende todas sus instancias: sus clientes dejan de poder entrar y ven el mensaje. La marca y los módulos no se tocan.'}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {bloqueado && (
            <div className="flex flex-wrap gap-2">
              {revendedor.mensaje && <p className="w-full text-sm text-muted-foreground">Mensaje: {revendedor.mensaje}</p>}
              <Button
                disabled={ocupado}
                onClick={() => hacer(async () => {
                  const r = await backoffice.revendedores.desbloquear(id)
                  mostrar(r.revendedor)
                  setResultados(r.resultados)
                  await cargarCatalogo()
                })}
              >
                <RotateCcw className="h-4 w-4" />Desbloquear
              </Button>
              <Button variant="outline" disabled={ocupado} onClick={() => { setMensaje(revendedor.mensaje); setBloqueando(true) }}>
                Reintentar el bloqueo
              </Button>
            </div>
          )}
          {!bloqueado && !bloqueando && (
            <Button variant="destructive" disabled={ocupado} onClick={() => setBloqueando(true)}>
              <Ban className="h-4 w-4" />Bloquear revendedor
            </Button>
          )}
          {bloqueando && (
            <div className="space-y-3">
              <div className="grid gap-2">
                <Label htmlFor="rev-mensaje">Mensaje que ven sus clientes</Label>
                <Input id="rev-mensaje" value={mensaje} maxLength={500} onChange={(e) => setMensaje(e.target.value)} />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="rev-confirmar">Escribí «{revendedor.nombre}» para confirmar</Label>
                <Input id="rev-confirmar" value={confirmar} maxLength={120} autoComplete="off" onChange={(e) => setConfirmar(e.target.value)} />
              </div>
              <div className="flex gap-2">
                <Button variant="destructive" disabled={ocupado || confirmar.trim() !== revendedor.nombre || !mensaje.trim()} onClick={seguir}>
                  Suspender {revendedor.instancias.length} {revendedor.instancias.length === 1 ? 'instancia' : 'instancias'}
                </Button>
                <Button variant="outline" disabled={ocupado} onClick={() => { setBloqueando(false); setConfirmar('') }}>Cancelar</Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Historial</CardTitle></CardHeader>
        <CardContent>
          {revendedor.historial.map((h) => (
            <div key={`${h.cuando}-${h.accion}-${h.detalle}`} className="border-b py-2 text-sm last:border-0">
              <p>{h.accion}{h.detalle && `: ${h.detalle}`}</p>
              <p className="text-xs text-muted-foreground">{new Date(h.cuando).toLocaleString('es-AR')} · {h.quien}</p>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  )
}
