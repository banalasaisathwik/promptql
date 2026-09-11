/** Filters already-discovered provider records; it never creates scan identifiers. */
export function filterDiscoveryItems<T>(
  items: readonly T[],
  query: string,
  searchableText: (item: T) => string,
): T[] {
  const normalized = query.trim().toLowerCase()
  if (!normalized) return [...items]
  return items.filter((item) => searchableText(item).toLowerCase().includes(normalized))
}
