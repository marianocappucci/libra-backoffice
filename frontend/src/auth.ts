// Sesión del superadmin del backoffice.
//
// Se usa la factory `createAuthContext` de libra-ui en vez de la instancia
// pre-configurada porque el backoffice tiene sus propias rutas (`/api/login`,
// `/api/me`, `/api/logout`) y su propio tipo de usuario — mismo caso que
// Contalibra y Restolibra.
import { createAuthContext } from 'libra-ui/AuthContext'

import type { Superadmin } from './api'

export const { AuthProvider, useAuth } = createAuthContext<Superadmin>({
  mePath: '/api/me',
  loginPath: '/api/login',
  logoutPath: '/api/logout',
})
