#!/usr/bin/env bash
# Arma y corre el `docker build` de la imagen del backoffice.
#
# Existe para que el build no dependa de acordarse de tres claves `--ssh`, dos
# `--build-arg` y dos tags. Los ids de `--ssh` salen del `Dockerfile` (un
# `--mount=type=ssh,id=X` por dependencia privada) y el test
# `backend/tests/test_construir_imagen.py` falla si este script y el Dockerfile
# dejan de coincidir.
#
# Uso:
#   scripts/construir_imagen.sh [--dry-run] [--permitir-rama] [TAG]
#
#   TAG             Tag de la imagen. Default: vAAAA.MM.DD-HHMMSS (hora local de
#                   quien construye). Ojo: el nombre del tag NO dice cuál imagen
#                   es más nueva; eso lo dicen el image ID y el APP_COMMIT.
#   --dry-run       Imprime el comando y no construye (no hace falta docker).
#   --permitir-rama Construye aunque el checkout no esté en `main`.
#
# Claves (una por `--ssh` id, NO un agente con las tres cargadas: con varias en
# un agente SSH las ofrece en orden y GitHub autentica con la primera que
# acepta, que puede no ser la del repo que se clona). Se pasan por variables de
# entorno con la RUTA de cada clave privada de sólo lectura; este archivo no
# lleva rutas ni contenido de claves:
#   LIBRA_SSH_KEY_LIBRACORE   deploy key de libracore
#   LIBRA_SSH_KEY_LIBRAAUTH   deploy key de libraauth
#   LIBRA_SSH_KEY_LIBRA_UI    deploy key de libra-ui
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGEN="libra-backoffice"

dry_run=0
permitir_rama=0
tag=""
tag_dado=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) dry_run=1 ;;
    --permitir-rama) permitir_rama=1 ;;
    -h|--help) sed -n '2,/^set -euo/p' "${BASH_SOURCE[0]}" | sed '$d' | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*) echo "Opción desconocida: $arg" >&2; exit 2 ;;
    *)
      [ "$tag_dado" -eq 0 ] || { echo "Un solo TAG, recibí '$tag' y '$arg'." >&2; exit 2; }
      tag="$arg"
      tag_dado=1
      ;;
  esac
done

if [ "$tag_dado" -eq 0 ]; then
  tag="v$(date +%Y.%m.%d-%H%M%S)"
fi
if ! printf '%s' "$tag" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$'; then
  echo "TAG inválido: '$tag' (letras, números, '.', '_' y '-'; máximo 128)." >&2
  exit 2
fi

# Los ids que el Dockerfile realmente monta, en el orden en que aparecen.
mapfile -t ids < <(grep -oE -- '--mount=type=ssh,id=[A-Za-z0-9_-]+' "$RAIZ/Dockerfile" | sed 's/.*id=//' | awk '!visto[$0]++')
if [ "${#ids[@]}" -eq 0 ]; then
  echo "El Dockerfile no declara ningún --mount=type=ssh,id=...; no hay nada que armar." >&2
  exit 1
fi

# id del Dockerfile -> variable con la ruta de su clave (libra-ui -> LIBRA_SSH_KEY_LIBRA_UI).
variable_de() {
  printf 'LIBRA_SSH_KEY_%s' "$(printf '%s' "$1" | tr 'a-z-' 'A-Z_')"
}

args=(docker build)
faltan=()
for id in "${ids[@]}"; do
  var="$(variable_de "$id")"
  ruta="${!var:-}"
  if [ -z "$ruta" ]; then
    faltan+=("$var (clave para --ssh $id)")
    continue
  fi
  if [ "$dry_run" -eq 0 ] && [ ! -r "$ruta" ]; then
    echo "$var apunta a un archivo que no existe o no se puede leer." >&2
    exit 1
  fi
  args+=(--ssh "$id=$ruta")
done
if [ "${#faltan[@]}" -gt 0 ]; then
  echo "Faltan variables de entorno con la ruta de la clave:" >&2
  printf '  %s\n' "${faltan[@]}" >&2
  exit 1
fi

# El commit que queda grabado en la imagen (`APP_COMMIT`) tiene que ser el del
# código que se construye: un árbol con cambios sin commitear lo haría mentir.
if [ -n "$(git -C "$RAIZ" status --porcelain --untracked-files=no)" ]; then
  echo "El árbol tiene cambios sin commitear: APP_COMMIT no describiría lo que se construye." >&2
  exit 1
fi
commit="$(git -C "$RAIZ" rev-parse --short HEAD)"
rama="$(git -C "$RAIZ" rev-parse --abbrev-ref HEAD)"
if [ "$rama" != "main" ] && [ "$permitir_rama" -eq 0 ]; then
  echo "El checkout está en '$rama', no en 'main' (lo que se despliega sale de main)." >&2
  echo "Si es a propósito: --permitir-rama." >&2
  exit 1
fi

args+=(
  --build-arg "APP_VERSION=$tag"
  --build-arg "APP_COMMIT=$commit"
  -t "$IMAGEN:$tag" -t "$IMAGEN:latest"
  "$RAIZ"
)

echo "Imagen $IMAGEN:$tag  (commit $commit, rama $rama)" >&2
if [ "$dry_run" -eq 1 ]; then
  printf '%q ' "${args[@]}"; printf '\n'
  exit 0
fi
"${args[@]}"
echo "Listo: $IMAGEN:$tag  APP_COMMIT=$commit" >&2
