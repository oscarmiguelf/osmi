// The part of Node's AsyncLocalStorage this app uses (i18n/giro.ts), without adding @types/node
declare module 'node:async_hooks' {
  export class AsyncLocalStorage<T> {
    getStore(): T | undefined;
    run<R>(store: T, callback: () => R): R;
  }
}
