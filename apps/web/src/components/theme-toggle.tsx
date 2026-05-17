import { Moon, Sun, Monitor } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import { useTheme } from "@/lib/theme";

export function ThemeToggle() {
  const { theme, resolved, setTheme } = useTheme();
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label="Đổi chủ đề" title="Đổi chủ đề">
          {resolved === "dark" ? <Moon aria-hidden /> : <Sun aria-hidden />}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onClick={() => setTheme("light")} aria-current={theme === "light"}>
          <Sun className="size-4" aria-hidden /> Sáng
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => setTheme("dark")} aria-current={theme === "dark"}>
          <Moon className="size-4" aria-hidden /> Tối
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => setTheme("system")} aria-current={theme === "system"}>
          <Monitor className="size-4" aria-hidden /> Theo hệ thống
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
