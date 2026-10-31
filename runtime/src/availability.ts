import { lstatSync, accessSync, constants } from 'node:fs';
import { join } from 'node:path';

/** Availability guard, not a sandbox: pins the actual selected directory/state/database. */
export class ProjectAvailability {
  private readonly identities: { path: string; dev: number; ino: number }[];
  constructor(project: string) {
    this.identities = [project, join(project, '.silicolab'), join(project, '.silicolab/session.sqlite')].map((path) => {
      const info = lstatSync(path); return { path, dev: info.dev, ino: info.ino };
    });
  }
  check() {
    try {
      for (const item of this.identities) {
        const info = lstatSync(item.path);
        if (info.isSymbolicLink() || info.dev !== item.dev || info.ino !== item.ino || !(info.mode & 0o222)) throw new Error('identity or write mode changed');
        accessSync(item.path, constants.R_OK | constants.W_OK);
      }
    } catch { throw new Error('项目目录不可访问、不可写或身份改变；已阻断新请求与产物写入，请重新定位核对'); }
  }
}
