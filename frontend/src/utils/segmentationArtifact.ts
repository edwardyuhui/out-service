export type SampleInterval = {
  startIndex: number;
  endIndex: number;
  count: number;
};

const validSampleIndex = (value: unknown, upperBound?: number | null): value is number =>
  typeof value === "number"
  && Number.isFinite(value)
  && Number.isInteger(value)
  && value >= 0
  && (upperBound === undefined || upperBound === null || value < upperBound);

export const mergeSelectedSampleIndices = (
  values: unknown,
  upperBound?: number | null
): SampleInterval[] => {
  if (!Array.isArray(values)) return [];

  const indices = [...new Set(values.filter((value) => validSampleIndex(value, upperBound)))]
    .sort((left, right) => left - right);
  if (!indices.length) return [];

  const intervals: SampleInterval[] = [];
  let startIndex = indices[0]!;
  let endIndex = startIndex;

  for (const index of indices.slice(1)) {
    if (index === endIndex + 1) {
      endIndex = index;
      continue;
    }
    intervals.push({ startIndex, endIndex, count: endIndex - startIndex + 1 });
    startIndex = index;
    endIndex = index;
  }

  intervals.push({ startIndex, endIndex, count: endIndex - startIndex + 1 });
  return intervals;
};
