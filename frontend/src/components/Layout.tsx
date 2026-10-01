// Shim sobre `libra-ui/Layout`, con el `useAuth` propio del backoffice.
//
// El branding es genérico a propósito: la misma imagen sirve a los seis
// productos y el nombre real llega por `/api/salud`. Poner "Gestiolibra" acá
// obligaría a una imagen por producto, que es justo lo que este repo evita.
import { Activity, Palette, Server, ShieldCheck } from 'lucide-react'
import { createLayout } from 'libra-ui/Layout'

import { useAuth } from '../auth'
import type { Superadmin } from '../api'

export const Layout = createLayout<Superadmin>({
  productName: 'Backoffice',
  productInitial: 'B',
  icon: Server,
  homeTo: '/instancias',
  navItems: [
    { to: '/instancias', label: 'Instancias', icon: Server },
    { to: '/salud', label: 'Salud', icon: Activity },
    // Sólo en los productos que la tienen (feature `apariencia`): el tema de la suite, ADR-007 de libra-ui.
    { to: '/apariencia', label: 'Apariencia', icon: Palette, module: 'apariencia' },
    { to: '/seguridad', label: 'Seguridad', icon: ShieldCheck },
  ],
  // Un backend viejo no manda `features`: se muestra todo, como antes (la pantalla misma contesta 404 si no existe).
  hasModule: (user, modulo) => user.features === undefined || user.features.includes(modulo),
  // El superadmin no tiene `name` ni `role`: el default del Layout mostraría
  // dos líneas vacías en el pie del sidebar.
  getUserName: (user) => user.username,
  useAuth,
})
