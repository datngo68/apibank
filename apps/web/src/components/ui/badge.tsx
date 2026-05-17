import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-1",
  {
    variants: {
      variant: {
        default: "border-transparent bg-secondary text-secondary-foreground",
        primary: "border-transparent bg-primary/10 text-primary dark:bg-primary/20",
        success: "border-transparent bg-success/10 text-success dark:bg-success/20",
        warning: "border-transparent bg-warning/15 text-warning dark:bg-warning/25",
        destructive: "border-transparent bg-destructive/10 text-destructive dark:bg-destructive/20",
        outline: "text-foreground",
        muted: "border-transparent bg-muted text-muted-foreground",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant, className }))} {...props} />;
}

export { badgeVariants };
