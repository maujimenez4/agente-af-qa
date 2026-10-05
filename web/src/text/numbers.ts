// Números en español con separador de miles también en los de cuatro cifras («2.350», no «2350»):
// Intl en es-ES no agrupa por debajo de 10.000 salvo con useGrouping: 'always'.
const NUMBER = new Intl.NumberFormat('es-ES', { useGrouping: 'always' })

export function formatNumber(value: number): string {
  return NUMBER.format(value)
}
