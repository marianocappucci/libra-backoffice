// Editar el nombre y el dominio de una instancia.
//
// Sólo esos dos campos, y no por recorte de alcance: son los únicos que el
// motor sabe cambiar sin recrear nada. El puerto y el nombre del contenedor
// están escritos en el `docker-compose.yml` de la instancia; el slug es el
// nombre de su directorio. Ofrecerlos acá sería ofrecer un botón que deja la
// metadata diciendo una cosa y el filesystem otra.
//
// Cambiar el dominio **sí** tiene efecto: el motor le arma el proxy nuevo en
// NPM. No borra el anterior, así que el dominio viejo sigue resolviendo hasta
// que alguien lo baje a mano.
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

import { ApiError, backoffice, type Instancia } from '../api'

type Props = {
  instancia: Instancia
  onEditada: () => Promise<unknown>
}

export function EditarInstancia({ instancia, onEditada }: Props) {
  const [abierto, setAbierto] = useState(false)
  const [nombre, setNombre] = useState(instancia.nombre)
  const [domain, setDomain] = useState(instancia.domain)
  const [guardando, setGuardando] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function abrir(v: boolean) {
    setAbierto(v)
    if (v) {
      // Al abrir se relee la instancia, no al montar: entre medio pudo haber
      // cambiado por otra acción de la misma pantalla.
      setNombre(instancia.nombre)
      setDomain(instancia.domain)
      setError(null)
    }
  }

  async function enviar(e: React.FormEvent) {
    e.preventDefault()
    setGuardando(true)
    setError(null)
    try {
      await backoffice.editar(instancia.slug, { nombre: nombre.trim(), domain: domain.trim() })
      await onEditada()
      setAbierto(false)
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Error de conexión.')
    } finally {
      setGuardando(false)
    }
  }

  const cambiaDominio = domain.trim() !== instancia.domain

  return (
    <Dialog open={abierto} onOpenChange={abrir}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          Editar
        </Button>
      </DialogTrigger>
      <DialogContent>
        <form onSubmit={enviar} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>Editar «{instancia.slug}»</DialogTitle>
            <DialogDescription>
              El slug, el puerto y el contenedor no se cambian desde acá: están escritos en el
              compose de la instancia.
            </DialogDescription>
          </DialogHeader>

          <div className="grid gap-2">
            <Label htmlFor="editar-nombre">Nombre</Label>
            <Input
              id="editar-nombre"
              required
              autoFocus
              value={nombre}
              onChange={(e) => setNombre(e.target.value)}
            />
          </div>

          <div className="grid gap-2">
            <Label htmlFor="editar-domain">Dominio</Label>
            <Input
              id="editar-domain"
              value={domain}
              onChange={(e) => setDomain(e.target.value)}
              placeholder="cliente.producto.com.ar"
            />
            {cambiaDominio && domain.trim() && (
              <p className="text-sm text-muted-foreground">
                Se le va a crear el proxy con SSL a <code>{domain.trim()}</code>.
                {instancia.domain && (
                  <> El proxy de <code>{instancia.domain}</code> queda en pie: bajalo a mano si ya
                  no va a usarse.</>
                )}
              </p>
            )}
          </div>

          {error && <p className="text-sm font-medium text-destructive">{error}</p>}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setAbierto(false)}>
              Cancelar
            </Button>
            <Button type="submit" disabled={guardando || !nombre.trim()}>
              {guardando ? 'Guardando…' : 'Guardar'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
