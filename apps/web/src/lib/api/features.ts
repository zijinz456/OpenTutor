import { request } from "./client";

export interface FeatureFlags {
  loom: boolean;
  lector: boolean;
  cat_pretest: boolean;
  browser: boolean;
  vision: boolean;
  notion_export: boolean;
}

export async function getFeatureFlags(): Promise<FeatureFlags> {
  return request<FeatureFlags>("/features");
}
