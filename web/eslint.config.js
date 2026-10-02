import js from '@eslint/js'
import { defineConfig, globalIgnores } from 'eslint/config'
import jsxA11y from 'eslint-plugin-jsx-a11y'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import globals from 'globals'
import tseslint from 'typescript-eslint'

// Reglas de seguridad del frontend (web/README.md, «Reglas»): el texto de la API
// se pinta como texto y la sesión nunca va al almacenamiento del navegador.
const HTML_INJECTION = 'El contenido de la API se muestra como texto: no se inserta HTML.'
const BROWSER_STORAGE = 'No se usa el almacenamiento del navegador: la sesión va como diga el contrato de T-55.'

export default defineConfig([
  globalIgnores(['dist', 'coverage']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
      jsxA11y.flatConfigs.recommended,
    ],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
    rules: {
      'no-restricted-syntax': [
        'error',
        { selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']", message: HTML_INJECTION },
        { selector: "AssignmentExpression[left.property.name=/^(innerHTML|outerHTML)$/]", message: HTML_INJECTION },
        { selector: "CallExpression[callee.property.name='insertAdjacentHTML']", message: HTML_INJECTION },
      ],
      'no-restricted-globals': [
        'error',
        { name: 'localStorage', message: BROWSER_STORAGE },
        { name: 'sessionStorage', message: BROWSER_STORAGE },
      ],
      'no-restricted-properties': [
        'error',
        { object: 'window', property: 'localStorage', message: BROWSER_STORAGE },
        { object: 'window', property: 'sessionStorage', message: BROWSER_STORAGE },
      ],
    },
  },
])
