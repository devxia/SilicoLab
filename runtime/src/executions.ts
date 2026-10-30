import { BACKGROUND_CONTEXT } from '@earendil-works/chord/context';
import { defineDoc, Harness, type HarnessOptions } from '@earendil-works/pi-durable';
import { openNodeSqliteStorage } from '@earendil-works/pi-durable/storage/sqlite/node';
import { ProjectFiles } from './inputs.ts';

export const ExecutionOwner = defineDoc<{ taskId: string }>({
  kind: 'silicolab.execution-owner', version: 1, scope: 'session',
  initial: () => ({ taskId: '' }), checkpointWhen: () => true,
});
type OpenKernel = (database: string, options: HarnessOptions) => Promise<Harness>;
const openKernel: OpenKernel = async (database, options) => Harness.open(await openNodeSqliteStorage(database), options, BACKGROUND_CONTEXT);

/** One serialized owner cache. Unpinned handles are borrowed only inside withStore. */
export class ExecutionStores {
  private readonly stores = new Map<string, Harness>();
  private readonly files: ProjectFiles;
  private readonly options: () => HarnessOptions;
  private readonly create: OpenKernel;
  private protectedTask: string | undefined;
  private line: Promise<unknown> = Promise.resolve();
  constructor(directory: string, options: () => HarnessOptions, create: OpenKernel = openKernel) {
    this.files = new ProjectFiles(directory); this.options = options; this.create = create;
  }
  pin(taskId: string | undefined) { this.protectedTask = taskId; }
  private serial<T>(operation: () => Promise<T>): Promise<T> {
    const result = this.line.then(operation);
    this.line = result.catch(() => {});
    return result;
  }
  private async acquire(taskId: string) {
    const cached = this.stores.get(taskId);
    if (cached) return cached;
    if (this.stores.size >= 8) {
      const evict = [...this.stores.keys()].find((id) => id !== this.protectedTask);
      if (!evict) throw new Error('运行存储缓存没有可释放位置');
      await this.retire(evict);
    }
    const directory = await this.files.directory(`.silicolab/runs/${taskId}`);
    const host = await this.create(`${directory}/session.sqlite`, this.options());
    try {
      await host.commit(async (tx) => {
        const owner = await tx.doc(ExecutionOwner);
        if (owner.taskId && owner.taskId !== taskId) throw new Error('运行存储任务身份不符');
        owner.taskId = taskId;
      }, BACKGROUND_CONTEXT);
      await host.root(BACKGROUND_CONTEXT);
      this.stores.set(taskId, host);
      return host;
    } catch (error) { await host.close(BACKGROUND_CONTEXT); throw error; }
  }
  /** Only the project scheduler's pinned active handle may outlive a borrowing operation. */
  openPinned(taskId: string) {
    return this.serial(async () => {
      if (this.protectedTask !== taskId) throw new Error('未获得任务执行位置');
      return this.acquire(taskId);
    });
  }
  withStore<T>(taskId: string, operation: (host: Harness) => Promise<T>) {
    return this.serial(async () => operation(await this.acquire(taskId)));
  }
  private async retire(taskId: string) {
    const host = this.stores.get(taskId);
    if (host) { await host.close(BACKGROUND_CONTEXT); this.stores.delete(taskId); }
  }
  close(taskId: string) { return this.serial(() => this.retire(taskId)); }
  closeAll() { return this.serial(async () => { for (const taskId of [...this.stores.keys()]) await this.retire(taskId); }); }
}
