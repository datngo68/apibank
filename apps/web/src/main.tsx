import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { HelmetProvider } from "react-helmet-async";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "sonner";
import { ThemeProvider } from "@/lib/theme";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ConfirmProvider } from "@/components/ui/confirm-dialog";
import { App } from "@/App";
import "@/styles/globals.css";
import "@/lib/i18n";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 30_000,
    },
  },
});

const root = document.getElementById("root");
if (!root) throw new Error("Missing #root element");

createRoot(root).render(
  <StrictMode>
    <ThemeProvider>
      <HelmetProvider>
        <QueryClientProvider client={queryClient}>
          <TooltipProvider delayDuration={200}>
            <ConfirmProvider>
              <BrowserRouter>
                <App />
                <Toaster richColors position="top-right" closeButton />
              </BrowserRouter>
            </ConfirmProvider>
          </TooltipProvider>
        </QueryClientProvider>
      </HelmetProvider>
    </ThemeProvider>
  </StrictMode>,
);
