// Shim sobre `libra-ui/Layout`, con el `useAuth` propio del backoffice.
//
// El branding es genérico a propósito: la misma imagen sirve a los seis
// productos y el nombre real llega por `/api/salud`. Poner "Gestiolibra" acá
// obligaría a una imagen por producto, que es justo lo que este repo evita.
import { Activity, Server } from 'lucide-react'
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
  ],
  // El superadmin no tiene `name` ni `role`: el default del Layout mostraría
  // dos líneas vacías en el pie del sidebar.
  getUserName: (user) => user.username,
  useAuth,
})
