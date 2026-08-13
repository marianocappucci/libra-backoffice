// Pantalla de UNA instancia: su ciclo de vida, su correo saliente y sus
// usuarios.
//
// Todo lo que se puede tocar acá está debajo del nombre de la instancia, y eso
// es deliberado: en un producto multi-cliente una pantalla de "correo
// saliente" sin instancia a la vista es ambigua, y esa ambigüedad se paga
// configurándole el servidor de correo al cliente equivocado.
import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ConfiguracionSmtp } from 'libra-ui/ConfiguracionSmtp'
import { Usuarios } from 'libra-ui/Usuarios'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { variantePorEstado } from '@/lib/servicio'

import { BajaInstancia } from '../components/BajaInstancia'
import { EditarInstancia } from '../components/EditarInstancia'
import { EstadoServicio } from '../components/EstadoServicio'
import {
  ApiError, backoffice, rutaSmtp, rutaUsuarios, type Instancia as TInstancia, type Plan,
} from '../api'

function describirError(err: unknown): string {
  if (err instanceof ApiError) return err.detail
  return 'Error de conexión.'
}

// Sólo el ciclo de vida del contenedor. El corte de servicio (pausar /
// suspender / activar) va en su propia tarjeta: comparte endpoint con estas
// tres pero no es lo mismo, y un botón «Suspender» al lado de «Detener» invita
// justo a la confusión que hay que evitar.
const ACCIONES = [
  { accion: 'start', label: 'Iniciar' },
  { accion: 'stop', label: 'Detener' },
  { accion: 'restart', label: 'Reiniciar' },
] as const

export function Instancia() {
  const { slug = '' } = useParams()
  const navegar = useNavigate()
  const [instancia, setInstancia] = useState<TInstancia | null>(null)
  const [planes, setPlanes] = useState<Plan[]>([])
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [ocupado, setOcupado] = useState(false)

  const releer = useCallback(async () => {
    setInstancia(await backoffice.instancia(slug))
  }, [slug])

  useEffect(() => {
    setCargando(true)
    Promise.all([backoffice.instancia(slug), backoffice.planes()])
      .then(([i, p]) => {
        setInstancia(i)
        setPlanes(p)
      })
      .catch((err) => setError(describirError(err)))
      .finally(() => setCargando(false))
  }, [slug])

  async function ejecutar(fn: () => Promise<TInstancia>, mensaje: string) {
    setOcupado(true)
    setError(null)
    setAviso(null)
    try {
      setInstancia(await fn())
      setAviso(mensaje)
    } catch (err) {
      setError(describirError(err))
    } finally {
      setOcupado(false)
    }
  }

  async function hacerBackup() {
    setOcupado(true)
    setError(null)
    setAviso(null)
    try {
      const { archivo } = await backoffice.backup(slug)
      setAviso(`Backup creado: ${archivo}`)
    } catch (err) {
      setError(describirError(err))
    } finally {
      setOcupado(false)
    }
  }

  if (cargando) return <p className="text-sm text-muted-foreground">Cargando…</p>
  if (!instancia) {
    return (
      <div className="space-y-4">
        <p className="text-sm font-medium text-destructive">{error ?? 'Instancia no encontrada.'}</p>
        <Button asChild variant="outline">
          <Link to="/instancias">Volver a instancias</Link>
        </Button>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex flex-wrap items-center gap-2">
            {instancia.nombre || instancia.slug}
            <Badge variant={instancia.estado === 'running' ? 'default' : 'outline'}>
              {instancia.estado}
            </Badge>
            {/* Los dos ejes juntos y sólo acá: un contenedor `running`
                suspendido no puede leerse como "todo bien". */}
            {instancia.servicio_estado !== 'activo' && (
              <Badge variant={variantePorEstado(instancia.servicio_estado)}>
                {instancia.servicio_estado}
              </Badge>
            )}
          </CardTitle>
          <CardDescription>
            {instancia.slug}
            {instancia.domain && ` · ${instancia.domain}`}
            {instancia.container && ` · ${instancia.container}`}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {error && <p className="text-sm font-medium text-destructive">{error}</p>}
          {aviso && <p className="text-sm font-medium text-primary">{aviso}</p>}

          <div className="flex flex-wrap items-center gap-2">
            {ACCIONES.map(({ accion, label }) => (
              <Button
                key={accion}
                variant="outline"
                size="sm"
                disabled={ocupado}
                onClick={() => ejecutar(() => backoffice.accion(slug, accion), `${label}: hecho.`)}
              >
                {label}
              </Button>
            ))}
            <Button variant="outline" size="sm" disabled={ocupado} onClick={hacerBackup}>
              Backup
            </Button>
            <EditarInstancia
              instancia={instancia}
              onEditada={async () => {
                await releer()
                setAviso('Datos actualizados.')
              }}
            />
            <BajaInstancia
              instancia={instancia}
              onDadaDeBaja={(backup) =>
                // La pantalla de una instancia que ya no existe no tiene qué
                // mostrar, así que se sale de acá. El aviso viaja en el estado
                // de la navegación porque la ruta del backup es la única copia
                // que queda de los datos del cliente.
                navegar('/instancias', {
                  replace: true,
                  state: {
                    aviso: backup
                      ? `Instancia «${instancia.slug}» dada de baja. Backup en ${backup}`
                      : `Instancia «${instancia.slug}» dada de baja, sin backup.`,
                  },
                })
              }
            />
          </div>

          {planes.length > 0 && (
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground">Plan</span>
              <Select
                value={instancia.plan || undefined}
                disabled={ocupado}
                onValueChange={(plan) =>
                  ejecutar(() => backoffice.cambiarPlan(slug, plan), 'Plan actualizado.')
                }
              >
                <SelectTrigger className="w-56">
                  <SelectValue placeholder="Sin plan asignado" />
                </SelectTrigger>
                <SelectContent>
                  {planes.map((p) => (
                    <SelectItem key={p.key} value={p.key}>
                      {p.label}
                      {p.precio != null && ` — $${p.precio.toLocaleString('es-AR')}`}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
        </CardContent>
      </Card>

      <EstadoServicio
        instancia={instancia}
        ocupado={ocupado}
        onAplicar={(accion, mensaje, label) =>
          ejecutar(
            () => backoffice.accion(slug, accion, mensaje),
            `Servicio: ${label.toLowerCase()}.`,
          )
        }
      />

      {/* `basePath` por instancia: es lo que hace que estos dos componentes
          compartidos escriban en el cliente correcto. */}
      <ConfiguracionSmtp basePath={rutaSmtp(slug)} />
      <Usuarios basePath={rutaUsuarios(slug)} />
    </div>
  )
}
