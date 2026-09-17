// A card and its quick shortcut represent the same tool. Coalesce clicks
// until the command settles, including the gap before progress events arrive.
export function createActionGate(onchange = () => {}) {
  const pending = new Map();
  return {
    run(id, task) {
      if (!id) return Promise.resolve().then(task);
      if (pending.has(id)) return pending.get(id);
      const promise = Promise.resolve().then(task).finally(() => {
        pending.delete(id);
        onchange([...pending.keys()]);
      });
      pending.set(id, promise);
      onchange([...pending.keys()]);
      return promise;
    },
  };
}
