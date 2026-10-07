// Huella de la API simulada con el formato del contrato (`ApproveIn` y `EditIn`: 64 hexadecimales, como la sha256 de
// la API real). Toda versión nueva (iterar, editar, suite) la usa: con otro formato, editar tras iterar daba 422.
export const randomFingerprint = (): string =>
  Array.from(crypto.getRandomValues(new Uint8Array(32)), (byte) => byte.toString(16).padStart(2, '0')).join('')
