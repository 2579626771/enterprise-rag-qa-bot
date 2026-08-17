import { afterEach, vi } from 'vitest';
function resetDom() {
    document.body.innerHTML = '';
    document.head.innerHTML = '';
}
afterEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    resetDom();
    vi.clearAllTimers();
    vi.useRealTimers();
});
