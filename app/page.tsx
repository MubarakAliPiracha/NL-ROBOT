'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Bot, Plus, Trash2, Sparkles } from 'lucide-react';
import { Logo } from '@/components/logo';
import { ThemeToggle } from '@/components/theme-toggle';
import { useSims } from '@/lib/sims';

const thumbGradients = [
  'from-sky-400 to-blue-600',
  'from-fuchsia-500 to-violet-600',
  'from-emerald-400 to-teal-600',
  'from-orange-400 to-rose-500',
];

function timeAgo(ts: number) {
  const s = Math.max(1, Math.round((Date.now() - ts) / 1000));
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

export default function HomePage() {
  const router = useRouter();
  const { sims, ready, create, remove } = useSims();

  const createAndOpen = () => router.push(`/sim/${create().id}`);

  return (
    <div className="min-h-screen bg-app">
      <header className="topbar sticky top-0 z-20 flex h-16 items-center justify-between px-5 shadow-md">
        <Logo />
        <div className="flex items-center gap-3">
          <ThemeToggle />
          <button
            onClick={createAndOpen}
            className="flex items-center gap-2 rounded-full bg-white px-4 py-2 text-sm font-bold text-brand shadow transition hover:scale-[1.03] hover:shadow-lg"
          >
            <Plus size={18} strokeWidth={3} />
            Create
          </button>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-5 py-8">
        <section className="hero-gradient relative overflow-hidden rounded-3xl p-8 text-white shadow-lift sm:p-12">
          <Sparkles className="absolute -right-4 -top-4 opacity-20" size={180} />
          <h1 className="max-w-xl text-3xl font-extrabold leading-tight sm:text-4xl">
            Tell a robot what to do. Watch it happen.
          </h1>
          <p className="mt-3 max-w-xl text-white/85">
            Upload a URDF, describe a motion in plain English, and simulate it with real physics.
          </p>
          <button
            onClick={createAndOpen}
            className="mt-6 inline-flex items-center gap-2 rounded-full bg-white px-6 py-3 text-base font-bold text-brand shadow-lg transition hover:scale-[1.03]"
          >
            <Plus size={20} strokeWidth={3} />
            Create new simulation
          </button>
        </section>

        <section className="mt-10">
          <h2 className="mb-4 flex items-center gap-2 text-lg font-bold text-brand">
            <Bot size={20} />
            Your simulations
          </h2>

          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
            <button
              onClick={createAndOpen}
              className="group flex min-h-[220px] flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed border-brand/50 bg-surface text-brand transition hover:border-brand hover:bg-brand/5"
            >
              <Plus size={34} className="transition group-hover:scale-110" />
              <span className="text-sm font-semibold">Create your first simulation</span>
            </button>

            {ready &&
              sims.map((sim, i) => (
                <div
                  key={sim.id}
                  className="group relative overflow-hidden rounded-2xl border border-line bg-surface shadow-card transition hover:-translate-y-0.5 hover:shadow-lift"
                >
                  <Link href={`/sim/${sim.id}`} className="block">
                    <div
                      className={`flex h-36 items-center justify-center bg-gradient-to-br ${thumbGradients[i % thumbGradients.length]}`}
                    >
                      <Bot size={56} className="text-white/90" />
                    </div>
                    <div className="p-4">
                      <div className="truncate font-semibold text-fg">{sim.name}</div>
                      <div className="mt-1 truncate text-xs text-muted">{sim.robotName}</div>
                      <div className="mt-1 text-xs text-muted">{timeAgo(sim.updatedAt)}</div>
                    </div>
                  </Link>
                  <button
                    onClick={() => remove(sim.id)}
                    aria-label={`Delete ${sim.name}`}
                    className="absolute right-2 top-2 rounded-full bg-black/35 p-2 text-white opacity-0 transition hover:bg-danger group-hover:opacity-100 focus:opacity-100"
                  >
                    <Trash2 size={15} />
                  </button>
                </div>
              ))}
          </div>
        </section>
      </main>
    </div>
  );
}
