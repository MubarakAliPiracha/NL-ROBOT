import { Bot } from 'lucide-react';

export function Logo() {
  return (
    <div className="flex items-center gap-2.5">
      <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-white text-brand shadow-sm">
        <Bot size={22} strokeWidth={2.4} />
      </div>
      <div className="leading-none">
        <div className="text-[10px] font-semibold uppercase tracking-[0.2em] text-white/80">Natural language</div>
        <div className="text-lg font-bold tracking-tight text-white">NL-Robot</div>
      </div>
    </div>
  );
}
