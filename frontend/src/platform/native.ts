import type { Engine } from '../features/codon/lib';
export type Draft = { name: string; text: string; species: string; motifs: string[]; engine: Engine };
export type WorkbenchSelection = { projectId: string; conversationId: string };
type NativeAPI = { save_selection?: (selection: WorkbenchSelection | null) => Promise<boolean>; desktop_status?: () => Promise<{ connected: boolean; backgroundPid: number | null; windowClose: string; quit: string }>; reconnect_background?: () => Promise<boolean>; quit_application?: () => Promise<boolean>; choose_project_directory: () => Promise<string | null>; bootstrap: () => Promise<{ desktop: boolean; draft: Draft | null; selection?: WorkbenchSelection | null }>; save_draft: (draft: Draft) => Promise<boolean>; copy_text: (text: string) => Promise<boolean>; open_export_directory: () => Promise<boolean>; save_export: (payload: { job_id: string; format: string; record_id: string | null; filename: string }) => Promise<{ saved: boolean; directory?: string }> };
declare global { interface Window { pywebview?: { api?: NativeAPI }; } }
export function nativeAPI() { return window.pywebview?.api; }
