'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Bot, Plus, Trash2, Github, Terminal, ArrowUp } from 'lucide-react';
import MinimalistDock, { type DockItem } from '@/components/ui/minimal-dock';
import { Logo } from '@/components/logo';
import { useSims } from '@/lib/sims';



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

  // Bottom dock: the page's primary navigation. Items act on real app state.
  const latest = [...sims].sort((a, b) => b.updatedAt - a.updatedAt)[0];
  const dockItems: DockItem[] = [
    {
      id: 'top',
      icon: <ArrowUp size={20} />,
      label: 'Back to top',
      onClick: () => window.scrollTo({ top: 0, behavior: 'smooth' }),
    },
    { id: 'new', icon: <Plus size={20} />, label: 'New simulation', onClick: createAndOpen },
    {
      id: 'latest',
      icon: <Bot size={20} />,
      label: latest ? `Open "${latest.name}"` : 'No simulations yet',
      onClick: latest ? () => router.push(`/sim/${latest.id}`) : undefined,
    },
    {
      id: 'console',
      icon: <Terminal size={20} />,
      label: latest ? 'Latest sim console' : 'Console (create a sim first)',
      onClick: latest ? () => router.push(`/sim/${latest.id}`) : undefined,
    },
    {
      id: 'github',
      icon: <Github size={20} />,
      label: 'Source on GitHub',
      onClick: () => window.open('https://github.com/007Aurick/NL-Robot-Sim', '_blank'),
    },
  ];

  return (
    <div className="min-h-screen bg-app">
      <header className="topbar sticky top-0 z-20 flex h-16 items-center justify-between px-5 shadow-md">
        <Logo />
        <div className="flex items-center gap-3">
          <button
            onClick={createAndOpen}
            className="flex items-center gap-2 border border-brand/60 bg-transparent px-4 py-2 text-sm font-bold text-brand transition hover:bg-brand/10"
          >
            <Plus size={18} strokeWidth={3} />
            Create
          </button>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-5 py-8">
        <section className="hero-gradient relative overflow-hidden p-8 sm:p-10">
          <p className="text-xs text-muted">nl-robot @ ros2-humble : gazebo-fortress</p>
          <h1 className="cursor-blink mt-3 max-w-xl text-2xl font-bold leading-tight text-fg sm:text-3xl">
            $ tell a robot what to do
          </h1>
          <p className="mt-3 max-w-xl text-muted">
            Upload a URDF, describe a motion in plain English, and it runs on real ROS 2
            interfaces: /cmd_vel, FollowJointTrajectory, /scan.
          </p>
          <button
            onClick={createAndOpen}
            className="mt-6 inline-flex items-center gap-2 border border-brand bg-brand/10 px-5 py-2.5 text-sm font-bold text-brand transition hover:bg-brand/20"
          >
            <Plus size={16} strokeWidth={3} />
            create new simulation
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
              sims.map((sim) => (
                <div
                  key={sim.id}
                  className="group relative overflow-hidden rounded-2xl border border-line bg-surface shadow-card transition hover:-translate-y-0.5 hover:shadow-lift"
                >
                  <Link href={`/sim/${sim.id}`} className="block">
                    <div className="flex h-36 items-center justify-center border-b border-line bg-surface-alt">
                      <Bot size={48} className="text-brand/70" />
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

      <div className="fixed bottom-5 left-1/2 z-30 -translate-x-1/2">
        <MinimalistDock items={dockItems} />
      </div>
    </div>
  );
}
