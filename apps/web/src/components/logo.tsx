import { Wallet } from "lucide-react";

export function Logo({ className }: { className?: string }) {
  return (
    <span className={className}>
      <span className="inline-flex size-7 items-center justify-center rounded-md bg-primary text-primary-foreground shadow-sm">
        <Wallet className="size-4" aria-hidden />
      </span>
      <span className="ml-2 align-middle text-base font-semibold tracking-tight">APIBank</span>
    </span>
  );
}
