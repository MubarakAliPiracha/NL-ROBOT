'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import { Plus, Github, Terminal, ArrowUp, Play, MoreVertical, Pencil, Copy, Trash2 } from 'lucide-react';
import MinimalistDock, { type DockItem } from '@/components/ui/minimal-dock';
import { SplashScreen } from '@/components/ui/splash-screen';
import { HeroReplay } from '@/components/ui/hero-replay';
import { NlLogoMark } from '@/components/ui/nl-logo';
import { Logo } from '@/components/logo';
import { useSims, type Sim } from '@/lib/sims';
import { STARTING_POINTS, EXAMPLE_COMMANDS, warehouseWorld } from '@/lib/presets';

function timeAgo(ts: number) {
  const s = Math.max(1, Math.round((Date.now() - ts) / 1000));
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

function SimCard({
  sim,
  onOpen,
  onRename,
  onDuplicate,
  onDelete,
}: {
  sim: Sim;
  onOpen: () => void;
  onRename: (name: string) => void;
  onDuplicate: () => void;
  onDelete: () => void;
}) {
  const [renaming, setRenaming] = useState(false);
  const [draft, setDraft] = useState(sim.name);

  return (
    <div className="group relative overflow-hidden rounded-2xl border border-line bg-surface transition hover:border-brand/50">
      <button onClick={onOpen} className="block w-full text-left focus-visible:outline focus-visible:outline-1 focus-visible:outline-brand">
        <div className="flex h-36 items-center justify-center overflow-hidden border-b border-line bg-surfaceAlt">
          {sim.thumb ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={sim.thumb} alt="" className="h-full w-full object-cover" />
          ) : (
            <NlLogoMark className="h-12 w-12 text-brand/70" />
          )}
        </div>
        <div className="p-4">
          {renaming ? (
            <input
              autoFocus
              value={draft}
              onClick={(e) => e.stopPropagation()}
              onChange={(e) => setDraft(e.target.value)}
              onBlur={() => {
                setRenaming(false);
                if (draft.trim()) onRename(draft.trim());
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
                if (e.key === 'Escape') setRenaming(false);
              }}
              className="w-full border border-line bg-app px-1.5 py-0.5 text-sm font-semibold text-fg outline-none focus:border-brand"
            />
          ) : (
            <div className="truncate font-semibold text-fg">{sim.name}</div>
          )}
          <div className="mt-1 truncate text-xs text-muted">{sim.robotName}</div>
          <div className="mt-1 text-xs text-muted">{timeAgo(sim.updatedAt)}</div>
        </div>
      </button>

      <DropdownMenu.Root>
        <DropdownMenu.Trigger asChild>
          <button
            aria-label={`Options for ${sim.name}`}
            className="absolute right-2 top-2 rounded-md border border-line bg-app/80 p-1.5 text-muted opacity-0 transition hover:text-fg focus-visible:opacity-100 focus-visible:outline focus-visible:outline-1 focus-visible:outline-brand group-hover:opacity-100"
          >
            <MoreVertical size={14} />
          </button>
        </DropdownMenu.Trigger>
        <DropdownMenu.Portal>
          <DropdownMenu.Content
            align="end"
            sideOffset={4}
            className="z-40 min-w-[140px] border border-line bg-surface p-1 text-xs shadow-lift"
          >
            <DropdownMenu.Item
              onSelect={() => {
                setDraft(sim.name);
                setRenaming(true);
              }}
              className="flex cursor-pointer items-center gap-2 px-2 py-1.5 text-fg outline-none data-[highlighted]:bg-brand/10 data-[highlighted]:text-brand"
            >
              <Pencil size={12} /> Rename
            </DropdownMenu.Item>
            <DropdownMenu.Item
              onSelect={onDuplicate}
              className="flex cursor-pointer items-center gap-2 px-2 py-1.5 text-fg outline-none data-[highlighted]:bg-brand/10 data-[highlighted]:text-brand"
            >
              <Copy size={12} /> Duplicate
            </DropdownMenu.Item>
            <DropdownMenu.Separator className="my-1 h-px bg-line" />
            <DropdownMenu.Item
              onSelect={onDelete}
              className="flex cursor-pointer items-center gap-2 px-2 py-1.5 text-danger outline-none data-[highlighted]:bg-danger/15"
            >
              <Trash2 size={12} /> Delete
            </DropdownMenu.Item>
          </DropdownMenu.Content>
        </DropdownMenu.Portal>
      </DropdownMenu.Root>
    </div>
  );
}

export default function HomePage() {
  const router = useRouter();
  const { sims, ready, create, duplicate, update, remove } = useSims();

  const createAndOpen = () => router.push(`/sim/${create().id}`);
  const watchLive = () =>
    router.push(
      `/sim/${create({ world: warehouseWorld(), pendingCommand: 'Drive forward until you see the wall, then turn left' }).id}`,
    );

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
      icon: <NlLogoMark className="h-5 w-5" />,
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
      <SplashScreen />
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

      <main className="mx-auto max-w-6xl px-5 py-8 pb-28">
        {/* 1. Hero: the product working, copy demoted beside it. */}
        <section className="hero-gradient grid gap-6 p-6 sm:p-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] lg:items-center">
          <HeroReplay />
          <div className="min-w-0">
            <p className="text-xs text-muted">nl-robot @ ros2-humble : gazebo-fortress</p>
            <h1 className="cursor-blink mt-2 text-2xl font-bold leading-tight text-fg sm:text-3xl">
              $ tell a robot what to do
            </h1>
            <p className="font-prose mt-3 max-w-md text-sm text-muted">
              Upload a URDF, describe a motion in plain English, and it runs on real ROS 2 interfaces:{' '}
              <span className="font-mono text-fg/90">/cmd_vel</span>,{' '}
              <span className="font-mono text-fg/90">FollowJointTrajectory</span>,{' '}
              <span className="font-mono text-fg/90">/scan</span>.
            </p>
            <button
              onClick={watchLive}
              className="mt-5 inline-flex items-center gap-2 border border-brand bg-brand/10 px-5 py-2.5 text-sm font-bold text-brand transition hover:bg-brand/20"
            >
              <Play size={15} />
              watch this run live
            </button>
          </div>
        </section>

        {/* 2. Start with a robot, not a blank scene. */}
        <section className="mt-8">
          <h2 className="mb-3 text-xs font-bold uppercase tracking-widest text-brand">Start with a robot</h2>
          <div className="grid gap-3 sm:grid-cols-3">
            {STARTING_POINTS.map((s) => (
              <button
                key={s.key}
                onClick={() => router.push(`/sim/${create(s.preset()).id}`)}
                className="border border-line bg-surface p-4 text-left transition hover:border-brand focus-visible:outline focus-visible:outline-1 focus-visible:outline-brand"
              >
                <div className="font-semibold text-fg">{s.title}</div>
                <p className="font-prose mt-1 text-xs text-muted">{s.blurb}</p>
              </button>
            ))}
          </div>
        </section>

        {/* 3. Example commands - click one, it creates the sim and runs it. */}
        <section className="mt-8">
          <h2 className="mb-3 text-xs font-bold uppercase tracking-widest text-brand">Or just say it</h2>
          <div className="flex flex-wrap gap-2">
            {EXAMPLE_COMMANDS.map((c) => (
              <button
                key={c.label}
                onClick={() => router.push(`/sim/${create({ ...c.preset(), pendingCommand: c.command }).id}`)}
                className="border border-line bg-surfaceAlt px-3 py-1.5 text-xs text-fg transition hover:border-brand hover:text-brand focus-visible:outline focus-visible:outline-1 focus-visible:outline-brand"
              >
                <span className="text-brand">$ </span>
                {c.label}
              </button>
            ))}
          </div>
        </section>

        {/* 4. Your simulations - demoted below the entry points. */}
        <section className="mt-10">
          <h2 className="mb-4 flex items-center gap-2 text-lg font-bold text-brand">
            <NlLogoMark className="h-5 w-5" />
            Your simulations
          </h2>

          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
            {ready && !sims.length && (
              <button
                onClick={createAndOpen}
                className="group flex min-h-[220px] flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed border-brand/50 bg-surface text-brand transition hover:border-brand hover:bg-brand/5"
              >
                <Plus size={34} className="transition group-hover:scale-110" />
                <span className="text-sm font-semibold">Create your first simulation</span>
              </button>
            )}

            {ready &&
              sims.map((sim) => (
                <SimCard
                  key={sim.id}
                  sim={sim}
                  onOpen={() => router.push(`/sim/${sim.id}`)}
                  onRename={(name) => update(sim.id, { name, named: true })}
                  onDuplicate={() => {
                    duplicate(sim.id);
                  }}
                  onDelete={() => remove(sim.id)}
                />
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
