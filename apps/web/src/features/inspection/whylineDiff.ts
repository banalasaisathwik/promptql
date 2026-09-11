export type DiffLine = { kind: 'context' | 'removed' | 'added', text: string }

/**
 * A minimal line-based diff (longest common subsequence) between an observed
 * hunk and a proposed hunk, both already returned by the backend. This only
 * decides how to *display* two existing strings side by side as +/- lines;
 * it never generates code.
 */
export function computeLineDiff(oldText: string, newText: string): DiffLine[] {
  const oldLines = oldText.split('\n')
  const newLines = newText.split('\n')
  const oldLength = oldLines.length
  const newLength = newLines.length

  const commonSuffixLength: number[][] = Array.from({ length: oldLength + 1 }, () =>
    new Array<number>(newLength + 1).fill(0),
  )
  for (let i = oldLength - 1; i >= 0; i -= 1) {
    for (let j = newLength - 1; j >= 0; j -= 1) {
      commonSuffixLength[i][j] = oldLines[i] === newLines[j]
        ? commonSuffixLength[i + 1][j + 1] + 1
        : Math.max(commonSuffixLength[i + 1][j], commonSuffixLength[i][j + 1])
    }
  }

  const diff: DiffLine[] = []
  let i = 0
  let j = 0
  while (i < oldLength && j < newLength) {
    if (oldLines[i] === newLines[j]) {
      diff.push({ kind: 'context', text: oldLines[i] })
      i += 1
      j += 1
    } else if (commonSuffixLength[i + 1][j] >= commonSuffixLength[i][j + 1]) {
      diff.push({ kind: 'removed', text: oldLines[i] })
      i += 1
    } else {
      diff.push({ kind: 'added', text: newLines[j] })
      j += 1
    }
  }
  while (i < oldLength) {
    diff.push({ kind: 'removed', text: oldLines[i] })
    i += 1
  }
  while (j < newLength) {
    diff.push({ kind: 'added', text: newLines[j] })
    j += 1
  }
  return diff
}
