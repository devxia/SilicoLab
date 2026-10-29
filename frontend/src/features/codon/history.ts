import { ACTIVE, type JobSummary } from './lib';

export const MAX_DELETE_BATCH = 1000;
export function canDeleteJob(job: Pick<JobSummary, 'status'>) { return !ACTIVE.includes(job.status); }
export function eligibleSelection(ids: readonly string[], jobs: readonly JobSummary[]) {
  const eligible = new Set(jobs.filter(canDeleteJob).map(job => job.id));
  return [...new Set(ids)].filter(id => eligible.has(id));
}
