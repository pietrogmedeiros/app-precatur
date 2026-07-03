"use client";

import type { FunnelStage } from "@/lib/api";
import { formatNumber } from "@/lib/utils";

const INK = ["hsl(var(--chart-1))", "hsl(var(--chart-3))", "hsl(var(--chart-4))"];

export function FunnelChart({ data }: { data: FunnelStage[] }) {
  const max = Math.max(...data.map((d) => d.count), 1);

  return (
    <div className="flex h-[260px] flex-col justify-center gap-4 px-2">
      {data.map((stage, i) => {
        // Width proportional to the top of the funnel; min 8% so small stages stay visible.
        const pct = Math.max((stage.count / max) * 100, 8);
        const prev = i > 0 ? data[i - 1].count : null;
        const rate = prev && prev > 0 ? Math.round((stage.count / prev) * 100) : null;

        return (
          <div key={stage.stage} className="flex flex-col items-center gap-1.5">
            <div className="flex items-baseline gap-2 text-xs">
              <span className="text-muted-foreground">{stage.stage}</span>
              <span className="font-semibold text-foreground">{formatNumber(stage.count)}</span>
              {rate !== null && (
                <span className="text-[11px] text-muted-foreground">({rate}%)</span>
              )}
            </div>
            <div
              className="h-10 rounded-md transition-[width] duration-300"
              style={{ width: `${pct}%`, backgroundColor: INK[i % INK.length] }}
            />
          </div>
        );
      })}
    </div>
  );
}
