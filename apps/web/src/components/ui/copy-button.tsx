import * as React from "react";
import { Check, Copy } from "lucide-react";
import { Button, type ButtonProps } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export interface CopyButtonProps extends Omit<ButtonProps, "children"> {
  value: string;
  label?: string;
}

export function CopyButton({ value, label = "Copy", className, ...props }: CopyButtonProps) {
  const [copied, setCopied] = React.useState(false);

  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard có thể bị block trong iframe; im lặng */
    }
  };

  return (
    <Button
      variant="outline"
      size="sm"
      onClick={onCopy}
      aria-live="polite"
      className={cn("gap-1.5", className)}
      {...props}
    >
      {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
      {copied ? "Đã copy" : label}
    </Button>
  );
}
