import { NlLogoMark } from '@/components/ui/nl-logo';

export function Logo() {
  return (
    <div className="flex items-center gap-2.5">
      <NlLogoMark className="h-9 w-9 shrink-0 text-brand" />
      <div className="leading-none">
        <div className="text-[10px] font-semibold uppercase tracking-[0.2em] text-muted">Natural language</div>
        <div className="text-lg font-bold tracking-tight text-fg">NL-Robot</div>
      </div>
    </div>
  );
}
