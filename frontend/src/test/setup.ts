import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

// jsdom no implementa estas tres APIs y los componentes de shadcn (que
// usan Radix por debajo) las tocan al montar. Sin los polyfills, cualquier
// pantalla con un Select o un Dialog revienta con un TypeError que no
// tiene nada que ver con lo que se esta probando.
if (!window.matchMedia) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches: false, media: query, onchange: null,
      addEventListener: vi.fn(), removeEventListener: vi.fn(),
      addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn(),
    }),
  })
}

if (!globalThis.ResizeObserver) {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
}

if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = vi.fn()
}

// jsdom NO tiene motor de layout: implementa `document.createRange()` pero
// el Range que devuelve no trae `getBoundingClientRect`. El `data-table`
// de libra-ui mide ahi el ancho de la columna de acciones y revienta con
// un TypeError en un layout effect.
//
// Se pone un polyfill en vez de tocar libra-ui: en jsdom cualquier medicion
// da cero igual, asi que saltearla en el componente daria exactamente el
// mismo resultado, pero cambiando codigo compartido por seis productos para
// acomodar al entorno de tests.
if (typeof Range !== 'undefined' && !Range.prototype.getBoundingClientRect) {
  const cero = () => ({
    x: 0, y: 0, width: 0, height: 0, top: 0, right: 0, bottom: 0, left: 0,
    toJSON: () => ({}),
  }) as DOMRect
  Range.prototype.getBoundingClientRect = cero
  Range.prototype.getClientRects = () => Object.assign([], { item: () => null }) as unknown as DOMRectList
}
