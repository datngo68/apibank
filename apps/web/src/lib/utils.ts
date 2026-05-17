import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatVnd(amount: number | string | null | undefined): string {
  if (amount === null || amount === undefined || amount === "") return "—";
  const num = typeof amount === "string" ? Number(amount) : amount;
  if (!Number.isFinite(num)) return "—";
  return new Intl.NumberFormat("vi-VN").format(num) + " ₫";
}

/** ISO datetime string không có timezone marker → coi như UTC.
 * Backend trả `datetime.now(UTC)` nhưng cột DB không gắn tzinfo, nên JSON
 * ra dạng `2026-05-16T17:26:38.795871` (không `Z`) — JS parse như local time
 * gây sai 7 tiếng. Hàm này chuẩn hoá lại trước khi `new Date()`. */
function parseDate(value: string | Date): Date {
  if (value instanceof Date) return value;
  // Có sẵn timezone marker (Z hoặc +hh:mm / -hh:mm sau phần T)
  const hasTz = /(?:Z|[+-]\d{2}:?\d{2})$/.test(value);
  const normalized = hasTz ? value : `${value.replace(" ", "T")}Z`;
  return new Date(normalized);
}

export function formatDateTime(value: string | Date | null | undefined): string {
  if (!value) return "—";
  const date = parseDate(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("vi-VN", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Asia/Ho_Chi_Minh",
  }).format(date);
}

export function relativeTime(value: string | Date | null | undefined): string {
  if (!value) return "—";
  const date = parseDate(value);
  const diffMs = Date.now() - date.getTime();
  const sec = Math.round(diffMs / 1000);
  const abs = Math.abs(sec);
  const rtf = new Intl.RelativeTimeFormat("vi-VN", { numeric: "auto" });
  if (abs < 60) return rtf.format(-sec, "second");
  if (abs < 3600) return rtf.format(-Math.round(sec / 60), "minute");
  if (abs < 86400) return rtf.format(-Math.round(sec / 3600), "hour");
  return rtf.format(-Math.round(sec / 86400), "day");
}
