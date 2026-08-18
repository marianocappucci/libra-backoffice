// Códigos de acceso a la demo pública de una instancia (libraauth v0.26.0).
//
// **El código se ve una sola vez.** El motor guarda su sha256 y devuelve sólo
// el prefijo de 4 caracteres, así que después de emitirlo no hay forma de
// releerlo: si se perdió, se revoca y se emite otro. Toda la pantalla está
// construida alrededor de ese hecho — el recuadro con el código emitido no se
// cierra solo, y avisa que es la única vez.
//
// La instancia es la que sabe si es una demo: en las que no lo son el router
// no está montado y contesta 404. Por eso el error de "no es una demo" se
// muestra como información y no como falla.
import { useCallback, useEffect, useState } from 'react'
import { KeyRound, Copy, Check } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { ApiError, api } from '../api'

export type CodigoDemo = {
  id: number
  prefijo: string
  etiqueta: string
  emitido_por: string
  creado_at: string | null
  expires_at: string | null
  ultimo_uso: string | null
  usos: number
  usos_max: number
  estado: 'vigente' | 'vencido' | 'agotado' | 'revocado'
}

const VARIANTE: Record<CodigoDemo['estado'], 'default' | 'outline' | 'secondary' | 'destructive'> = {
  vigente: 'default',
  vencido: 'outline',
  agotado: 'secondary',
  revocado: 'destructive',
}

// `dd-mm-aaaa HH:MM`, el formato de la familia. Helper único de esta pantalla:
// la base sigue guardando ISO y lo que se formatea es la presentación.
function fecha(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  const dd = String(d.getDate()).padStart(2, '0')
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const mi = String(d.getMinutes()).padStart(2, '0')
  return `${dd}-${mm}-${d.getFullYear()} ${hh}:${mi}`
}

export function CodigosDemo({ basePath }: { basePath: string }) {
  const [codigos, setCodigos] = useState<CodigoDemo[]>([])
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [noEsDemo, setNoEsDemo] = useState(false)
  const [emitido, setEmitido] = useState<string | null>(null)
  const [copiado, setCopiado] = useState(false)
  const [ocupado, setOcupado] = useState(false)

  const [etiqueta, setEtiqueta] = useState('')
  const [dias, setDias] = useState(7)
  const [usosMax, setUsosMax] = useState(10)

  const releer = useCallback(async () => {
    try {
      const r = await api.get<{ codigos: CodigoDemo[] }>(basePath)
      setCodigos(r.codigos)
      setNoEsDemo(false)
    } catch (err) {
      // Un 404 acá no es un error: es una instancia de cliente, que no monta
      // el router porque no tiene demo que abrir.
      if (err instanceof ApiError && err.status === 404) setNoEsDemo(true)
      else setError(err instanceof ApiError ? err.detail : 'Error de conexión.')
    } finally {
      setCargando(false)
    }
  }, [basePath])

  useEffect(() => { void releer() }, [releer])

  async function emitir() {
    setOcupado(true)
    setError(null)
    setCopiado(false)
    try {
      const r = await api.post<CodigoDemo & { codigo: string }>(
        basePath, { etiqueta, dias, usos_max: usosMax })
      setEmitido(r.codigo)
      setEtiqueta('')
      await releer()
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Error de conexión.')
    } finally {
      setOcupado(false)
    }
  }

  async function revocar(id: number) {
    setOcupado(true)
    setError(null)
    try {
      await api.del(`${basePath}/${id}`)
      await releer()
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Error de conexión.')
    } finally {
      setOcupado(false)
    }
  }

  if (cargando) return <p className="text-sm text-muted-foreground">Cargando…</p>

  if (noEsDemo) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Esta instancia no es una demo</CardTitle>
          <CardDescription>
            Los códigos de acceso existen sólo en la instancia de demostración del
            producto, que es la que se abre con <code>DEMO_MODE</code> y{' '}
            <code>DEMO_USERNAME</code>. Una instancia de cliente no tiene demo que abrir.
          </CardDescription>
        </CardHeader>
      </Card>
    )
  }

  return (
    <div className="space-y-6">
      {error && <p className="text-sm font-medium text-destructive">{error}</p>}

      {/* 🔴 El código emitido, y el aviso de que es la única vez. No se cierra
          solo ni se va al recargar la lista: si desaparece antes de que
          alguien lo copie, hay que emitir otro. */}
      {emitido && (
        <Card className="border-primary">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <KeyRound className="h-4 w-4" /> Código emitido
            </CardTitle>
            <CardDescription>
              Copialo ahora: <strong>es la única vez que se muestra</strong>. De la base
              sale sólo su hash, así que no hay forma de recuperarlo después — si se
              pierde, se revoca y se emite otro.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-wrap items-center gap-3">
            <code className="rounded bg-muted px-3 py-2 text-lg font-bold tracking-widest">
              {emitido}
            </code>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                void navigator.clipboard?.writeText(emitido)
                setCopiado(true)
              }}
            >
              {copiado
                ? <><Check className="mr-1 h-4 w-4" /> Copiado</>
                : <><Copy className="mr-1 h-4 w-4" /> Copiar</>}
            </Button>
            <Button type="button" variant="ghost" onClick={() => setEmitido(null)}>
              Listo, ya lo guardé
            </Button>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Emitir un código</CardTitle>
          <CardDescription>
            Con vencimiento y tope de ingresos. La etiqueta no la mira ninguna
            validación: existe para poder decidir después cuál revocar.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form
            className="grid gap-4 sm:grid-cols-[1fr_auto_auto_auto] sm:items-end"
            onSubmit={(e) => { e.preventDefault(); void emitir() }}
          >
            <div className="grid gap-2">
              <Label htmlFor="etiqueta-codigo">Para quién</Label>
              <Input
                id="etiqueta-codigo"
                value={etiqueta}
                onChange={(e) => setEtiqueta(e.target.value)}
                placeholder="Estudio Pérez"
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="dias-codigo">Días</Label>
              <Input
                id="dias-codigo"
                type="number"
                min={1}
                className="sm:w-24"
                value={dias}
                onChange={(e) => setDias(Number(e.target.value))}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="usos-codigo">Ingresos</Label>
              <Input
                id="usos-codigo"
                type="number"
                min={1}
                className="sm:w-24"
                value={usosMax}
                onChange={(e) => setUsosMax(Number(e.target.value))}
              />
            </div>
            <Button type="submit" disabled={ocupado || dias < 1 || usosMax < 1}>
              Emitir
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Códigos emitidos</CardTitle>
          <CardDescription>
            Se listan por prefijo: el código entero no se guarda. Revocar no borra la
            fila — interesa saber que existió y cuántas veces se usó.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {codigos.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Todavía no se emitió ninguno. Sin códigos vigentes, nadie puede entrar a
              la demo.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Código</TableHead>
                  <TableHead>Para quién</TableHead>
                  <TableHead>Estado</TableHead>
                  <TableHead>Ingresos</TableHead>
                  <TableHead>Vence</TableHead>
                  <TableHead>Último uso</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {codigos.map((c) => (
                  <TableRow key={c.id}>
                    <TableCell className="font-mono">{c.prefijo}…</TableCell>
                    <TableCell>{c.etiqueta || '—'}</TableCell>
                    <TableCell>
                      <Badge variant={VARIANTE[c.estado]}>{c.estado}</Badge>
                    </TableCell>
                    <TableCell>{c.usos} / {c.usos_max}</TableCell>
                    <TableCell>{fecha(c.expires_at)}</TableCell>
                    <TableCell>{fecha(c.ultimo_uso)}</TableCell>
                    <TableCell className="text-right">
                      {/* Sólo lo que todavía puede dejar entrar: revocar un
                          vencido no cambia nada y el botón sugeriría que sí. */}
                      {c.estado === 'vigente' && (
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          disabled={ocupado}
                          onClick={() => void revocar(c.id)}
                        >
                          Revocar
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
