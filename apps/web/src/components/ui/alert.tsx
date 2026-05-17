import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { AlertCircle, CheckCircle2, Info, AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";

const alertVariants = cva(
  "relative w-full rounded-lg border p-4 text-sm [&>svg]:absolute [&>svg]:left-4 [&>svg]:top-4 [&>svg]:size-4 [&>svg+div]:translate-y-[-3px] [&:has(svg)]:pl-11",
  {
    variants: {
      variant: {
        default: "bg-card text-card-foreground",
        info: "border-blue-500/30 bg-blue-500/5 text-blue-700 dark:text-blue-300 [&>svg]:text-blue-500",
        success: "border-success/40 bg-success/5 text-success [&>svg]:text-success",
        warning: "border-warning/40 bg-warning/5 text-warning [&>svg]:text-warning",
        destructive: "border-destructive/40 bg-destructive/5 text-destructive [&>svg]:text-destructive",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

const icons = {
  default: Info,
  info: Info,
  success: CheckCircle2,
  warning: AlertTriangle,
  destructive: AlertCircle,
};

export interface AlertProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof alertVariants> {
  hideIcon?: boolean;
}

export const Alert = React.forwardRef<HTMLDivElement, AlertProps>(
  ({ className, variant = "default", hideIcon, children, ...props }, ref) => {
    const Icon = icons[variant ?? "default"];
    return (
      <div ref={ref} role="alert" className={cn(alertVariants({ variant }), className)} {...props}>
        {hideIcon ? null : <Icon aria-hidden />}
        {children}
      </div>
    );
  },
);
Alert.displayName = "Alert";

export const AlertTitle = React.forwardRef<HTMLParagraphElement, React.HTMLAttributes<HTMLParagraphElement>>(
  ({ className, ...props }, ref) => (
    <h5 ref={ref} className={cn("mb-1 font-semibold leading-none", className)} {...props} />
  ),
);
AlertTitle.displayName = "AlertTitle";

export const AlertDescription = React.forwardRef<
  HTMLParagraphElement,
  React.HTMLAttributes<HTMLParagraphElement>
>(({ className, ...props }, ref) => (
  <div ref={ref} className={cn("text-sm leading-relaxed [&_p]:leading-relaxed", className)} {...props} />
));
AlertDescription.displayName = "AlertDescription";
