import { defineStore } from "pinia";
import { ref } from "vue";
import type { DatasetItem, DatasetProfile } from "../types/api";
import { listDatasets } from "../api/datasets";

const DATASET_LIST_PAGE_SIZE = 100;
const UNKNOWN_DATASET_NAME = "未知数据集";

export const useDatasetStore = defineStore("dataset", () => {
  const activeDataset = ref<DatasetItem | null>(null);
  const activeProfile = ref<DatasetProfile | null>(null);
  const datasetsList = ref<DatasetItem[]>([]);
  const datasetNamesLoaded = ref(false);
  let datasetNamesLoadPromise: Promise<void> | null = null;

  function setActiveDataset(ds: DatasetItem | null) {
    activeDataset.value = ds;
  }

  function setDatasetsList(list: DatasetItem[]) {
    datasetsList.value = list;
  }

  function resolveDatasetName(datasetId?: string | null): string {
    if (!datasetId) return UNKNOWN_DATASET_NAME;
    return datasetsList.value.find((dataset) => dataset.id === datasetId)?.name || UNKNOWN_DATASET_NAME;
  }

  async function ensureDatasetNamesLoaded(): Promise<void> {
    if (datasetNamesLoaded.value) return;
    if (datasetNamesLoadPromise) return datasetNamesLoadPromise;

    datasetNamesLoadPromise = (async () => {
      const datasets: DatasetItem[] = [];
      let page = 1;

      try {
        while (true) {
          const response = await listDatasets({ page, page_size: DATASET_LIST_PAGE_SIZE });
          datasets.push(...response.items);
          if (response.items.length < DATASET_LIST_PAGE_SIZE) break;
          page += 1;
        }
        setDatasetsList(datasets);
        datasetNamesLoaded.value = true;
      } catch {
        // Name resolution is display-only. Keep any existing names and let
        // consumers render the safe, non-ID fallback when the list is unavailable.
      } finally {
        datasetNamesLoadPromise = null;
      }
    })();

    return datasetNamesLoadPromise;
  }

  function setProfile(profile: DatasetProfile | null) {
    activeProfile.value = profile;
  }

  return {
    activeDataset,
    activeProfile,
    datasetsList,
    datasetNamesLoaded,
    setActiveDataset,
    setDatasetsList,
    setProfile,
    resolveDatasetName,
    ensureDatasetNamesLoaded,
  };
});
