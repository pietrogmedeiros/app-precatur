import { cn } from "@/lib/utils";

// PRECATUR crest — reproduced as line-art SVG so it scales cleanly and inherits
// the monochrome theme via currentColor.
export function PrecaturMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 40 48"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinejoin="round"
      strokeLinecap="round"
      className={cn("h-5 w-5", className)}
      aria-hidden="true"
    >
      {/* shield outline */}
      <path d="M20 2.5 L36 7.8 V24 C36 34.6 29 42.6 20 45.5 C11 42.6 4 34.6 4 24 V7.8 Z" />
      {/* crown arc + divider */}
      <path d="M13.5 16.5 c1.6 -3.4 11.4 -3.4 13 0" />
      <path d="M12 17 h16" />
      {/* central emblem */}
      <path d="M20 21 c-3.4 1.8 -3.4 8.2 0 10 c3.4 -1.8 3.4 -8.2 0 -10 Z" />
    </svg>
  );
}
