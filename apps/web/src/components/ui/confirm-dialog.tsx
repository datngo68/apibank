/**
 * ConfirmDialog — modal xác nhận tái sử dụng, thay cho `window.confirm`.
 *
 * Cách dùng:
 *
 *     const confirm = useConfirm();
 *     const ok = await confirm({
 *       title: "Xoá webhook",
 *       description: "Hành động không thể hoàn tác.",
 *       confirmText: "Xoá",
 *       variant: "destructive",
 *     });
 *     if (ok) action.mutate();
 *
 * Mount `<ConfirmProvider>` 1 lần ở root (cạnh Toaster). Provider giữ 1
 * instance Dialog dùng chung — caller không cần render dialog ở từng nơi.
 */

import * as React from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

export interface ConfirmOptions {
  title: string;
  description?: React.ReactNode;
  confirmText?: string;
  cancelText?: string;
  variant?: "primary" | "destructive";
}

type Resolver = (value: boolean) => void;

interface InternalState {
  open: boolean;
  options: ConfirmOptions;
  resolver: Resolver | null;
}

const DEFAULT_OPTIONS: ConfirmOptions = {
  title: "Xác nhận",
  confirmText: "Xác nhận",
  cancelText: "Huỷ",
  variant: "primary",
};

const ConfirmContext = React.createContext<((opts: ConfirmOptions) => Promise<boolean>) | null>(
  null,
);

export function ConfirmProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = React.useState<InternalState>({
    open: false,
    options: DEFAULT_OPTIONS,
    resolver: null,
  });

  const confirm = React.useCallback((options: ConfirmOptions) => {
    return new Promise<boolean>((resolve) => {
      setState({
        open: true,
        options: { ...DEFAULT_OPTIONS, ...options },
        resolver: resolve,
      });
    });
  }, []);

  const settle = React.useCallback((value: boolean) => {
    setState((prev) => {
      prev.resolver?.(value);
      return { ...prev, open: false, resolver: null };
    });
  }, []);

  const handleOpenChange = React.useCallback(
    (next: boolean) => {
      if (!next) {
        settle(false);
      }
    },
    [settle],
  );

  const { open, options } = state;
  const confirmVariant = options.variant === "destructive" ? "destructive" : "primary";

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      <Dialog open={open} onOpenChange={handleOpenChange}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{options.title}</DialogTitle>
            {options.description ? (
              <DialogDescription>{options.description}</DialogDescription>
            ) : null}
          </DialogHeader>
          <DialogFooter className="gap-2">
            <Button variant="ghost" onClick={() => settle(false)}>
              {options.cancelText}
            </Button>
            <Button variant={confirmVariant} onClick={() => settle(true)} autoFocus>
              {options.confirmText}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </ConfirmContext.Provider>
  );
}

/**
 * Hook trả về function `confirm(options) => Promise<boolean>`.
 * Throw nếu chưa mount `ConfirmProvider`.
 */
export function useConfirm() {
  const ctx = React.useContext(ConfirmContext);
  if (!ctx) {
    throw new Error("useConfirm must be used inside <ConfirmProvider>");
  }
  return ctx;
}
