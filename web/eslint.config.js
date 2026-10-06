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
const DOWNLOAD = 'Para descargar un texto, usa downloadText() (src/security/download.ts).'
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
        { selector: "JSXAttribute[name.name='srcDoc']", message: HTML_INJECTION },
        // href, src, action o formAction con una expresión: solo un literal o safeHref(…).
        {
          selector:
            "JSXAttribute[name.name=/^(href|src|srcSet|action|formAction|xlinkHref|poster|data|ping|cite)$/] > JSXExpressionContainer > :not(Literal, TemplateLiteral[expressions.length=0], CallExpression[callee.name='safeHref'])",
          message: UNSAFE_LINK,
        },
        // xlink:href con namespace y spread de props en elementos con URL: la regla de arriba no los ve.
        // <button> e <input> quedan fuera: los componentes del sistema les reenvían props (Chip, TextField).
        { selector: "JSXAttribute[name.type='JSXNamespacedName'][name.name.name='href']", message: UNSAFE_LINK },
        // Enlaces fuera de JSX: un href asignado a mano o un blob: solo en src/security/download.ts (downloadText).
        { selector: "AssignmentExpression[left.property.name='href']", message: `${UNSAFE_LINK} ${DOWNLOAD}` },
        { selector: "AssignmentExpression[left.property.value='href']", message: `${UNSAFE_LINK} ${DOWNLOAD}` },
        { selector: "AssignmentExpression[left.property.quasis.0.value.raw='href']", message: `${UNSAFE_LINK} ${DOWNLOAD}` },
        {
          selector: "CallExpression[callee.property.name=/^setAttribute(NS)?$/][arguments.length>=2] > Literal[value=/^(xlink:)?(href|src|action|formaction)$/i]",
          message: `${UNSAFE_LINK} ${DOWNLOAD}`,
        },
        {
          selector:
            "CallExpression[callee.property.name=/^setAttribute(NS)?$/][arguments.length>=2] > TemplateLiteral[quasis.0.value.raw=/^(xlink:)?(href|src|action|formaction)$/i]",
          message: `${UNSAFE_LINK} ${DOWNLOAD}`,
        },
        { selector: "CallExpression[callee.computed=true][callee.property.value=/^setAttribute(NS)?$/]", message: `${UNSAFE_LINK} ${DOWNLOAD}` },
        { selector: "CallExpression[callee.property.name='createObjectURL']", message: DOWNLOAD },
        { selector: "CallExpression[callee.computed=true][callee.property.value='createObjectURL']", message: DOWNLOAD },
        { selector: "VariableDeclarator > ObjectPattern > Property[key.name='createObjectURL']", message: DOWNLOAD },
        {
          selector:
            "JSXOpeningElement[name.name=/^(a|img|form|iframe|use|image|object|embed|source|video|audio|area|base|link|track)$/] > JSXSpreadAttribute",
          message: `${UNSAFE_LINK} Sin spread de props en elementos con URL.`,
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
        { object: 'window', property: 'open', message: UNSAFE_LINK },
        { object: 'location', property: 'assign', message: UNSAFE_LINK },
        { object: 'location', property: 'replace', message: UNSAFE_LINK },
      ],
    },
  },
])
