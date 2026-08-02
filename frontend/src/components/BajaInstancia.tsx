// Baja de una instancia.
//
// Lo que esto ejecuta del otro lado: `docker compose down -v` —el contenedor y
// **su volumen**— más un `rmtree` del directorio del cliente, más la
// eliminación del proxy en NPM. No hay papelera. De ahí las dos fricciones
// deliberadas de esta pantalla: hay que escribir el slug, y el backup viene
// tildado.
//
// El backend valida la confirmación por su cuenta (`confirmar_slug` tiene que
// coincidir con la ruta). Que el botón se habilite recién al coincidir es
// comodidad; que la baja no ocurra sin eso es del servidor.
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

import { ApiError, backoffice, type Instancia } from '../api'

type Props = {
  instancia: Instancia
  /** Se llama con el resultado ya en la mano: la pantalla de la instancia deja
   *  de tener sentido apenas la instancia no existe. */
  onDadaDeBaja: (backup: string | null) => void
}

export function BajaInstancia({ instancia, onDadaDeBaja }: Props) {
  const [abierto, setAbierto] = useState(false)
  const [confirmacion, setConfirmacion] = useState('')
  const [hacerBackup, setHacerBackup] = useState(true)
  const [borrando, setBorrando] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function abrir(v: boolean) {
    setAbierto(v)
    if (v) {
      setConfirmacion('')
      setHacerBackup(true)
      setError(null)
    }
  }

  async function enviar(e: React.FormEvent) {
    e.preventDefault()
    setBorrando(true)
    setError(null)
    try {
      const { backup } = await backoffice.baja(instancia.slug, {
        confirmar_slug: confirmacion.trim(),
        hacer_backup: hacerBackup,
      })
      onDadaDeBaja(backup)
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Error de conexión.')
      setBorrando(false)
    }
  }

  const coincide = confirmacion.trim() === instancia.slug

  return (
    <Dialog open={abierto} onOpenChange={abrir}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" className="text-destructive hover:text-destructive">
          Dar de baja
        </Button>
      </DialogTrigger>
      <DialogContent>
        <form onSubmit={enviar} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>Dar de baja «{instancia.slug}»</DialogTitle>
            <DialogDescription>
              Borra el contenedor con su volumen, el directorio de datos del cliente y su proxy en
              NPM. No se puede deshacer.
            </DialogDescription>
          </DialogHeader>

          <label className="flex items-center gap-2 text-sm">
            <Checkbox
              checked={hacerBackup}
              onCheckedChange={(v) => setHacerBackup(v === true)}
            />
            Hacer un backup antes de borrar
          </label>
          {!hacerBackup && (
            <p className="rounded-md border border-destructive/50 p-3 text-sm">
              Sin backup, los datos de <strong>{instancia.nombre || instancia.slug}</strong> no se
              recuperan de ningún lado.
            </p>
          )}

          <div className="grid gap-2">
            <Label htmlFor="baja-confirmar">
              Escribí <code>{instancia.slug}</code> para confirmar
            </Label>
            <Input
              id="baja-confirmar"
              autoFocus
              autoComplete="off"
              value={confirmacion}
              onChange={(e) => setConfirmacion(e.target.value)}
            />
          </div>

          {error && <p className="text-sm font-medium text-destructive">{error}</p>}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setAbierto(false)}>
              Cancelar
            </Button>
            <Button type="submit" variant="destructive" disabled={borrando || !coincide}>
              {borrando ? 'Dando de baja…' : 'Dar de baja'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
