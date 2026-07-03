"use client";

import {
  Cell,
  Funnel,
  FunnelChart as RechartsFunnelChart,
  LabelList,
  ResponsiveContainer,
} from "recharts";
import type { FunnelStage } from "@/lib/api";
import { formatNumber } from "@/lib/utils";

const INK = ["hsl(var(--chart-1))", "hsl(var(--chart-3))", "hsl(var(--chart-4))"];

export function FunnelChart({ data }: { data: FunnelStage[] }) {
  return (
    <ResponsiveContainer width="100%" height={260}>
      <RechartsFunnelChart margin={{ top: 8, right: 96, bottom: 8, left: 96 }}>
        <Funnel dataKey="count" data={data} isAnimationActive>
          {data.map((_, i) => (
            <Cell key={i} fill={INK[i % INK.length]} />
          ))}
          {/* Stage name outside, to the left */}
          <LabelList
            position="left"
            dataKey="stage"
            stroke="none"
            offset={12}
            className="fill-muted-foreground"
            fontSize={12}
          />
          {/* Count outside, to the right */}
          <LabelList
            position="right"
            dataKey="count"
            stroke="none"
            offset={12}
            formatter={(v: number) => formatNumber(v)}
            className="fill-foreground"
            fontSize={13}
            fontWeight={600}
          />
        </Funnel>
      </RechartsFunnelChart>
    </ResponsiveContainer>
  );
}
