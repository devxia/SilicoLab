import type { Engine } from '../features/codon/lib';
export type Draft = { name: string; text: string; species: string; motifs: string[]; engine: Engine };
type NativeAPI = { bootstrap: () => Promise<{ desktop: boolean; draft: Draft | null }>; save_draft: (draft: Draft) => Promise<boolean>; copy_text: (text: string) => Promise<boolean>; open_export_directory: () => Promise<boolean>; save_export: (payload: { job_id: string; format: string; record_id: string | null; filename: string }) => Promise<{ saved: boolean; directory?: string }> };
declare global { interface Window { pywebview?: { api?: NativeAPI }; } }
export function nativeAPI() { return window.pywebview?.api; }
