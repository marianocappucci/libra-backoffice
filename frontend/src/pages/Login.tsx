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
  //
  // Segundo factor (F2, libraauth v0.36.0): la sonda dice si este backoffice
  // tiene `ADMIN_PANEL_TOTP_SECRET`; sólo entonces aparece el campo del código.
  // La misma imagen corre con y sin 2FA según su `.env`, por eso se pregunta
  // en runtime y no se decide en el build.
  totpPath: '/api/login/opciones',
  // El detalle real del backend: con segundo factor el 401 dice "usuario,
  // contraseña o código", y el 429 del bloqueo dice cuánto esperar. El
  // genérico de libra-ui taparía los dos.
  formatError: (err) => err.detail,
})
