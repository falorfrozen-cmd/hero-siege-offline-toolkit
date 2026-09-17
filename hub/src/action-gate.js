export class ToolBusyError extends Error {
  constructor() {
    super('This tool is busy. Wait for its current operation to finish, then try again.');
    this.name = 'ToolBusyError';
  }
}

// Command arguments are flat IPC values. Property order must not make two
// identical clicks different, but launching from source is a different request.
export function operationKey(command, args = {}) {
  return JSON.stringify([command, Object.entries(args).sort(([a], [b]) => a.localeCompare(b))]);
}

// Duplicate requests share their result. Different operations on the same tool
// are refused until it is free, never silently treated as the first operation.
export function createActionGate(onchange = () => {}) {
  const pending = new Map();
  return {
    run(id, operation, task) {
      if (!id) return Promise.resolve().then(task);
      const active = pending.get(id);
      if (active) {
        return active.operation === operation ? active.promise : Promise.reject(new ToolBusyError());
      }
      const promise = Promise.resolve().then(task).finally(() => {
        pending.delete(id);
        onchange([...pending.keys()]);
      });
      pending.set(id, { operation, promise });
      onchange([...pending.keys()]);
      return promise;
    },
  };
}
