"use client";

import {
  Bar,
  BarChart,
  Cell,
  LabelList,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from "recharts";
import type { FunnelStage } from "@/lib/api";
import { formatNumber } from "@/lib/utils";

const INK = ["hsl(var(--chart-1))", "hsl(var(--chart-3))", "hsl(var(--chart-4))"];

export function FunnelChart({ data }: { data: FunnelStage[] }) {
  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={data} layout="vertical" margin={{ left: 8, right: 40, top: 8, bottom: 8 }}>
        <XAxis type="number" hide />
        <YAxis
          type="category"
          dataKey="stage"
          tickLine={false}
          axisLine={false}
          width={96}
          tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 12 }}
        />
        <Bar dataKey="count" radius={[6, 6, 6, 6]} barSize={34}>
          {data.map((_, i) => (
            <Cell key={i} fill={INK[i % INK.length]} />
          ))}
          <LabelList
            dataKey="count"
            position="right"
            formatter={(v: number) => formatNumber(v)}
            className="fill-foreground"
            fontSize={12}
            fontWeight={600}
          />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
