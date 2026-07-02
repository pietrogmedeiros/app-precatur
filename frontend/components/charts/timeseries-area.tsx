"use client";

import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { TimeseriesPoint } from "@/lib/api";
import { formatNumber } from "@/lib/utils";

function monthLabel(ym: string): string {
  const [y, m] = ym.split("-");
  const meses = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"];
  return `${meses[Number(m) - 1] ?? m}/${y.slice(2)}`;
}

export function TimeseriesArea({ data }: { data: TimeseriesPoint[] }) {
  const shaped = data.map((d) => ({ ...d, label: monthLabel(d.month) }));

  return (
    <ResponsiveContainer width="100%" height={280}>
      <AreaChart data={shaped} margin={{ left: 4, right: 12, top: 8, bottom: 4 }}>
        <defs>
          <linearGradient id="fillLeads" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="hsl(var(--chart-1))" stopOpacity={0.35} />
            <stop offset="95%" stopColor="hsl(var(--chart-1))" stopOpacity={0.02} />
          </linearGradient>
          <linearGradient id="fillConv" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="hsl(var(--chart-3))" stopOpacity={0.3} />
            <stop offset="95%" stopColor="hsl(var(--chart-3))" stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid vertical={false} stroke="hsl(var(--border))" strokeDasharray="3 3" />
        <XAxis
          dataKey="label"
          tickLine={false}
          axisLine={false}
          tickMargin={8}
          tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 12 }}
        />
        <YAxis
          tickLine={false}
          axisLine={false}
          width={32}
          tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 12 }}
        />
        <Tooltip
          cursor={{ stroke: "hsl(var(--border))" }}
          contentStyle={{
            background: "hsl(var(--card))",
            border: "1px solid hsl(var(--border))",
            borderRadius: 8,
            fontSize: 12,
            color: "hsl(var(--foreground))",
          }}
          formatter={(v: number, name) => [formatNumber(v), name === "leads" ? "Leads" : "Convertidos"]}
        />
        <Area
          type="monotone"
          dataKey="leads"
          stroke="hsl(var(--chart-1))"
          strokeWidth={2}
          fill="url(#fillLeads)"
        />
        <Area
          type="monotone"
          dataKey="convertidos"
          stroke="hsl(var(--chart-3))"
          strokeWidth={2}
          fill="url(#fillConv)"
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
