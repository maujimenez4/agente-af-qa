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
const UNSAFE_LINK = 'Un enlace construido con datos pasa por safeHref() (src/security/safeHref.ts, PA-308): nunca javascript: ni data:.'
const BROWSER_STORAGE = 'No se usa el almacenamiento del navegador: la sesión va como diga el contrato de T-55.'

export default defineConfig([
  globalIgnores(['dist', 'coverage', 'mock-public', 'src/api/schema.d.ts', 'tools']),
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
      'no-eval': 'error',
      'no-implied-eval': 'error',
      'no-new-func': 'error',
      'no-restricted-syntax': [
        'error',
        { selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']", message: HTML_INJECTION },
        { selector: "AssignmentExpression[left.property.name=/^(innerHTML|outerHTML)$/]", message: HTML_INJECTION },
        { selector: "AssignmentExpression[left.property.value=/^(innerHTML|outerHTML)$/]", message: HTML_INJECTION },
        { selector: "CallExpression[callee.property.name='insertAdjacentHTML']", message: HTML_INJECTION },
        // href, src, action o formAction con una expresión: solo un literal o safeHref(…).
        {
          selector:
            "JSXAttribute[name.name=/^(href|src|action|formAction|xlinkHref)$/] > JSXExpressionContainer > :not(Literal, TemplateLiteral[expressions.length=0], CallExpression[callee.name='safeHref'])",
          message: UNSAFE_LINK,
        },
      ],
      'no-restricted-globals': [
        'error',
        { name: 'localStorage', message: BROWSER_STORAGE },
        { name: 'sessionStorage', message: BROWSER_STORAGE },
        { name: 'indexedDB', message: BROWSER_STORAGE },
      ],
      'no-restricted-properties': [
        'error',
        { object: 'window', property: 'localStorage', message: BROWSER_STORAGE },
        { object: 'window', property: 'sessionStorage', message: BROWSER_STORAGE },
        { object: 'window', property: 'indexedDB', message: BROWSER_STORAGE },
        { object: 'globalThis', property: 'localStorage', message: BROWSER_STORAGE },
        { object: 'globalThis', property: 'sessionStorage', message: BROWSER_STORAGE },
        { object: 'document', property: 'cookie', message: BROWSER_STORAGE },
        { object: 'document', property: 'write', message: HTML_INJECTION },
        { object: 'document', property: 'writeln', message: HTML_INJECTION },
      ],
    },
  },
])
