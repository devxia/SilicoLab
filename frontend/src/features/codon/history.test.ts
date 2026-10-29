import { describe, expect, it } from 'vitest';
import { canDeleteJob, eligibleSelection, MAX_DELETE_BATCH } from './history';
import { ApiError, type JobSummary } from './lib';

const job = (id: string, status = 'completed') => ({ id, status } as JobSummary);
describe('history deletion selection', () => {
  it('protects all active states and allows inactive states', () => {
    for (const status of ['queued', 'running', 'stopping']) expect(canDeleteJob(job('a', status))).toBe(false);
    for (const status of ['completed', 'partial', 'warning', 'failed', 'stopped', 'paused', 'interrupted']) expect(canDeleteJob(job('a', status))).toBe(true);
  });
  it('removes invisible, nonexistent, newly active and duplicate selections', () => {
    expect(eligibleSelection(['a', 'b', 'b', 'c', 'missing'], [job('b'), job('c', 'running')])).toEqual(['b']);
  });
  it('keeps explicit selection order and does not change the source lists', () => {
    const selected = ['b', 'a']; const jobs = [job('a'), job('b')];
    expect(eligibleSelection(selected, jobs)).toEqual(['b', 'a']);
    expect(selected).toEqual(['b', 'a']); expect(jobs.map(row => row.id)).toEqual(['a', 'b']);
  });
  it('uses a bounded batch size matching the API', () => expect(MAX_DELETE_BATCH).toBe(1000));
  it('preserves HTTP status for non-connectivity 404 handling', () => { const error = new ApiError('task gone', 404); expect(error).toBeInstanceOf(Error); expect(error.status).toBe(404); });
});
