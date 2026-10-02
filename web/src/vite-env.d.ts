/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** «1» activa la API simulada (MSW) en `npm run dev`. */
  readonly VITE_API_MOCK?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
