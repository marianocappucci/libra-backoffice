import { createLogin } from 'libra-ui/Login'

import { useAuth } from '../auth'
import type { Superadmin } from '../api'

export const Login = createLogin<Superadmin>({
  productName: 'Backoffice',
  productInitial: 'B',
  redirectTo: '/instancias',
  useAuth,
  // Sin `forgotPasswordPath`: las credenciales del superadmin salen del
  // entorno (`ADMIN_PANEL_USER`/`ADMIN_PANEL_PASSWORD`), no de una tabla, así
  // que no hay nada que recuperar por correo. Mostrar el enlace sería un link
  // a un 404.
})
