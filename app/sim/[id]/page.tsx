'use client';

import dynamic from 'next/dynamic';

// three.js needs the browser, so the workspace is client-only.
const SimWorkspace = dynamic(() => import('@/components/sim-workspace').then((m) => m.SimWorkspace), {
  ssr: false,
  loading: () => (
    <div className="flex min-h-screen items-center justify-center bg-app text-muted">Loading simulation…</div>
  ),
});

export default function SimPage() {
  return <SimWorkspace />;
}
