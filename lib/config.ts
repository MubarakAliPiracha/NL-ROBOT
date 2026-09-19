export const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://127.0.0.1:8000';
export const BACKEND_WS_URL = BACKEND_URL.replace(/^http/, 'ws') + '/ws';
