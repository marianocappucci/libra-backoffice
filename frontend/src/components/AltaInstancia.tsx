// Alta de una instancia nueva.
//
// El backoffice Jinja2 que este reemplazó tenía esta pantalla (`/clientes/nuevo`);
// la primera versión del SPA no, así que dar de alta un cliente volvía a ser
// entrar por SSH a correr `nuevo_cliente.py`.
//
// Dos cosas gobiernan el diseño de este formulario:
//
// 1. **Casi todo es opcional a propósito.** El motor deriva el slug del nombre,
//    toma el próximo puerto libre y genera la contraseña. Pedir esos tres
//    campos sería pedirle al humano que adivine lo que el host ya sabe, y cada
//    uno es una forma de equivocarse (un puerto ocupado, un slug con acentos).
//
//    **El CUIT es la excepción, y lo es porque el host no lo sabe.** Sin él la
//    instancia nace sin identidad fiscal y el panel del dueño no la puede
//    agrupar por razón social — le pasó a `contalibra-demo`, que hoy contesta
//    nombre y CUIT vacíos. "Después lo cargo desde Configuración" es
//    exactamente lo que no pasó. Para las demos, que no tienen CUIT, está el
//    check de abajo: explícito, para que no sea el camino de menor esfuerzo.
// 2. **La contraseña generada se ve una sola vez.** Vuelve en la respuesta del
//    alta y en ningún otro endpoint. Si esta pantalla la refrescara y siguiera
//    de largo, quedaría un admin al que sólo se entra leyendo
//    `clientes/<slug>/cliente.json` por SSH. Por eso el alta termina en un
//    panel de credenciales y no en una redirección.
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'

import { ApiError, backoffice, type AltaIn, type InstanciaCreada, type Plan } from '../api'

type Props = {
  planes: Plan[]
  /** Los slugs que ya existían al abrir el diálogo. Sirven para distinguir un
   *  alta que falló de una que el navegador no llegó a ver terminar. */
  slugsPrevios: string[]
  /** Vuelve a pedir el inventario y devuelve los slugs que hay ahora. */
  recargar: () => Promise<string[]>
}

const VACIO = {
  nombre: '', slug: '', domain: '', port: '',
  empresa_nombre: '', empresa_cuit: '', sin_identidad: false,
  admin_user: 'admin', admin_password: '', plan: '', setup_npm: true,
}

export function AltaInstancia({ planes, slugsPrevios, recargar }: Props) {
  const [abierto, setAbierto] = useState(false)
  const [campos, setCampos] = useState({ ...VACIO })
  const [creando, setCreando] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [huerfana, setHuerfana] = useState<string | null>(null)
  const [creada, setCreada] = useState<InstanciaCreada | null>(null)

  function set<K extends keyof typeof VACIO>(campo: K, valor: (typeof VACIO)[K]) {
    setCampos((c) => ({ ...c, [campo]: valor }))
  }

  function abrir(v: boolean) {
    setAbierto(v)
    if (!v) {
      // Cerrar el panel de credenciales las descarta: no hay dónde volver a
      // pedirlas. Se limpia recién acá, no al abrir, para que no parpadeen.
      setCampos({ ...VACIO })
      setError(null)
      setHuerfana(null)
      setCreada(null)
    }
  }

  async function enviar(e: React.FormEvent) {
    e.preventDefault()
    setCreando(true)
    setError(null)
    setHuerfana(null)

    const datos: AltaIn = { nombre: campos.nombre.trim() }
    if (campos.slug.trim()) datos.slug = campos.slug.trim()
    if (campos.domain.trim()) datos.domain = campos.domain.trim()
    if (campos.port.trim()) datos.port = Number(campos.port)
    if (campos.admin_user.trim()) datos.admin_user = campos.admin_user.trim()
    if (campos.admin_password) datos.admin_password = campos.admin_password
    if (campos.plan) datos.plan = campos.plan
    if (campos.empresa_nombre.trim()) datos.empresa_nombre = campos.empresa_nombre.trim()
    if (campos.empresa_cuit.trim()) datos.empresa_cuit = campos.empresa_cuit.trim()
    // Se manda sólo cuando está tildado. La validación del CUIT vive en el
    // motor y no se duplica acá: dos copias de una regla se separan, y la que
    // se separa es siempre la de la pantalla.
    if (campos.sin_identidad) datos.sin_identidad = true
    datos.setup_npm = campos.setup_npm

    try {
      setCreada(await backoffice.crear(datos))
      await recargar()
    } catch (err) {
      // Un 422 es el motor rechazando el alta: no se creó nada. Cualquier otra
      // cosa —un 502/504 del proxy, la conexión cortada— puede ser el alta
      // siguiendo su curso en el host mientras el navegador ya se dio por
      // vencido: `docker compose up` más la espera de la base más la emisión
      // del certificado pasan del minuto. Reintentar a ciegas ahí crearía un
      // segundo cliente o chocaría con un slug tomado, así que se mira.
      const status = err instanceof ApiError ? err.status : 0
      setError(err instanceof ApiError ? err.detail : 'Error de conexión.')
      if (status !== 422) {
        const nuevos = (await recargar().catch(() => [])).filter(
          (s) => !slugsPrevios.includes(s),
        )
        if (nuevos.length) setHuerfana(nuevos[0])
      }
    } finally {
      setCreando(false)
    }
  }

  return (
    <Dialog open={abierto} onOpenChange={abrir}>
      <DialogTrigger asChild>
        <Button size="sm">Nueva instancia</Button>
      </DialogTrigger>

      <DialogContent className="sm:max-w-lg">
        {creada ? (
          <Credenciales instancia={creada} onListo={() => abrir(false)} />
        ) : (
          <form onSubmit={enviar} className="grid gap-4">
            <DialogHeader>
              <DialogTitle>Nueva instancia</DialogTitle>
              <DialogDescription>
                Crea el directorio del cliente, levanta su contenedor, le aplica el plan y
                —si tiene dominio— le arma el proxy con SSL.
              </DialogDescription>
            </DialogHeader>

            <div className="grid gap-2">
              <Label htmlFor="alta-nombre">Nombre del cliente</Label>
              <Input
                id="alta-nombre"
                required
                autoFocus
                value={campos.nombre}
                onChange={(e) => set('nombre', e.target.value)}
                placeholder="ACME SA"
              />
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="grid gap-2">
                <Label htmlFor="alta-razon">Razón social</Label>
                <Input
                  id="alta-razon"
                  value={campos.empresa_nombre}
                  onChange={(e) => set('empresa_nombre', e.target.value)}
                  placeholder="igual al nombre"
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="alta-cuit">CUIT</Label>
                <Input
                  id="alta-cuit"
                  required={!campos.sin_identidad}
                  disabled={campos.sin_identidad}
                  value={campos.empresa_cuit}
                  onChange={(e) => set('empresa_cuit', e.target.value)}
                  placeholder="20-28993360-4"
                />
              </div>
            </div>

            <label className="flex items-start gap-2 text-sm text-muted-foreground">
              <Checkbox
                className="mt-0.5"
                checked={campos.sin_identidad}
                onCheckedChange={(v) => set('sin_identidad', v === true)}
              />
              <span>
                Es una demo, sin identidad fiscal. El panel del dueño no la va a poder agrupar
                por razón social y la va a mostrar como «sin identificar».
              </span>
            </label>

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="grid gap-2">
                <Label htmlFor="alta-slug">Slug</Label>
                <Input
                  id="alta-slug"
                  value={campos.slug}
                  onChange={(e) => set('slug', e.target.value)}
                  placeholder="se deriva del nombre"
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="alta-port">Puerto</Label>
                <Input
                  id="alta-port"
                  type="number"
                  value={campos.port}
                  onChange={(e) => set('port', e.target.value)}
                  placeholder="el próximo libre"
                />
              </div>
            </div>

            <div className="grid gap-2">
              <Label htmlFor="alta-domain">Dominio</Label>
              <Input
                id="alta-domain"
                value={campos.domain}
                onChange={(e) => set('domain', e.target.value)}
                placeholder="cliente.producto.com.ar (opcional)"
              />
              <label className="flex items-center gap-2 text-sm text-muted-foreground">
                <Checkbox
                  checked={campos.setup_npm}
                  disabled={!campos.domain.trim()}
                  onCheckedChange={(v) => set('setup_npm', v === true)}
                />
                Crear el proxy y emitir el certificado SSL
              </label>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="grid gap-2">
                <Label htmlFor="alta-user">Usuario admin</Label>
                <Input
                  id="alta-user"
                  value={campos.admin_user}
                  onChange={(e) => set('admin_user', e.target.value)}
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="alta-password">Contraseña admin</Label>
                <Input
                  id="alta-password"
                  type="text"
                  value={campos.admin_password}
                  onChange={(e) => set('admin_password', e.target.value)}
                  placeholder="vacío = se genera"
                />
              </div>
            </div>

            {planes.length > 0 && (
              <div className="grid gap-2">
                <Label htmlFor="alta-plan">Plan</Label>
                <Select value={campos.plan || undefined} onValueChange={(v) => set('plan', v)}>
                  <SelectTrigger id="alta-plan">
                    <SelectValue placeholder="Básico" />
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

            {error && <p className="text-sm font-medium text-destructive">{error}</p>}
            {huerfana && (
              <p className="rounded-md border border-destructive/50 p-3 text-sm">
                <strong>No reintentes todavía.</strong> Apareció la instancia{' '}
                <code>{huerfana}</code> en el inventario: el alta siguió en el host después de
                que se cortara la respuesta. La contraseña del admin no se puede recuperar desde
                acá — está en <code>clientes/{huerfana}/cliente.json</code> del VPS.
              </p>
            )}

            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => abrir(false)}>
                Cancelar
              </Button>
              <Button
                type="submit"
                disabled={
                  creando ||
                  !campos.nombre.trim() ||
                  (!campos.sin_identidad && !campos.empresa_cuit.trim())
                }
              >
                {creando ? 'Creando…' : 'Crear instancia'}
              </Button>
            </DialogFooter>
            {creando && (
              <p className="text-sm text-muted-foreground">
                Levanta el contenedor, espera a que inicialice su base y emite el certificado.
                Puede tardar más de un minuto: no cierres esta ventana.
              </p>
            )}
          </form>
        )}
      </DialogContent>
    </Dialog>
  )
}

/** El único lugar donde se ve la contraseña del admin de la instancia nueva. */
function Credenciales({
  instancia,
  onListo,
}: {
  instancia: InstanciaCreada
  onListo: () => void
}) {
  const [copiado, setCopiado] = useState(false)

  async function copiar() {
    await navigator.clipboard?.writeText(
      `${instancia.admin_user} / ${instancia.admin_password}` +
        (instancia.panel_token ? `\npanel token: ${instancia.panel_token}` : ''),
    )
    setCopiado(true)
  }

  return (
    <div className="grid gap-4">
      <DialogHeader>
        <DialogTitle>Instancia «{instancia.slug}» creada</DialogTitle>
        <DialogDescription>
          Anotá la contraseña y el panel token antes de cerrar: no hay ninguna pantalla que
          vuelva a mostrarlos. El panel token es el que va en el alta de esta sucursal en
          LibraPanel.
        </DialogDescription>
      </DialogHeader>

      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
        <dt className="text-muted-foreground">Usuario</dt>
        <dd className="font-mono">{instancia.admin_user}</dd>
        <dt className="text-muted-foreground">Contraseña</dt>
        <dd className="font-mono break-all">{instancia.admin_password}</dd>
        <dt className="text-muted-foreground">Plan</dt>
        <dd>{instancia.plan}</dd>
        {instancia.panel_token && (
          <>
            <dt className="text-muted-foreground">Panel token</dt>
            <dd className="font-mono break-all">{instancia.panel_token}</dd>
          </>
        )}
        <dt className="text-muted-foreground">Puerto</dt>
        <dd className="font-mono">{instancia.port}</dd>
        {instancia.domain && (
          <>
            <dt className="text-muted-foreground">Dominio</dt>
            <dd className="font-mono break-all">{instancia.domain}</dd>
          </>
        )}
      </dl>

      {instancia.proxy_ok === false && (
        <p className="rounded-md border border-destructive/50 p-3 text-sm">
          La instancia quedó creada, pero <strong>no se pudo armar el proxy</strong> para{' '}
          <code>{instancia.domain}</code>. El dominio no va a resolver hasta configurarlo a mano
          en Nginx Proxy Manager, apuntando al puerto {instancia.port}.
        </p>
      )}

      <DialogFooter>
        <Button type="button" variant="outline" onClick={copiar}>
          {copiado ? 'Copiado' : 'Copiar credenciales'}
        </Button>
        <Button type="button" onClick={onListo}>
          Listo
        </Button>
      </DialogFooter>
    </div>
  )
}
