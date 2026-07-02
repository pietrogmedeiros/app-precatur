"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { OwnerMetrics } from "@/lib/api";
import { formatNumber } from "@/lib/utils";

export function OwnerBar({ data }: { data: OwnerMetrics[] }) {
  return (
    <ResponsiveContainer width="100%" height={320}>
      <BarChart data={data} margin={{ left: 4, right: 8, top: 8, bottom: 4 }} barGap={4}>
        <CartesianGrid vertical={false} stroke="hsl(var(--border))" strokeDasharray="3 3" />
        <XAxis
          dataKey="owner"
          tickLine={false}
          axisLine={false}
          tickMargin={8}
          interval={0}
          tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 11 }}
        />
        <YAxis
          tickLine={false}
          axisLine={false}
          width={32}
          tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 12 }}
        />
        <Tooltip
          cursor={{ fill: "hsl(var(--muted))", opacity: 0.4 }}
          contentStyle={{
            background: "hsl(var(--card))",
            border: "1px solid hsl(var(--border))",
            borderRadius: 8,
            fontSize: 12,
            color: "hsl(var(--foreground))",
          }}
          formatter={(v: number, name) => [
            formatNumber(v),
            name === "total_leads" ? "Leads" : name === "qualificados" ? "Qualificados" : "Convertidos",
          ]}
        />
        <Legend
          iconType="circle"
          iconSize={8}
          wrapperStyle={{ fontSize: 12, color: "hsl(var(--muted-foreground))" }}
          formatter={(name) =>
            name === "total_leads" ? "Leads" : name === "qualificados" ? "Qualificados" : "Convertidos"
          }
        />
        <Bar dataKey="total_leads" fill="hsl(var(--chart-1))" radius={[4, 4, 0, 0]} />
        <Bar dataKey="qualificados" fill="hsl(var(--chart-3))" radius={[4, 4, 0, 0]} />
        <Bar dataKey="convertidos" fill="hsl(var(--chart-5))" radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}
