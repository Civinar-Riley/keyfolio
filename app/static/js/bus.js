/** 微型事件总线：跨组件 toast / 跳转。 */
const listeners = {};

export const bus = {
  on(ev, fn) { (listeners[ev] ||= []).push(fn); },
  emit(ev, ...args) { (listeners[ev] || []).forEach(fn => fn(...args)); },
};
