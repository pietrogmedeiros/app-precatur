"use client";

import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Pie, PieChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { formatBRL } from "@/lib/pricing";

// Paleta do app: monocromática, como o resto da interface. Os dois tons foram
// conferidos no validador — contraste e separação para daltonismo passam com
// folga (ΔE 27,7). Como são tons de cinza, identidade NUNCA depende só da cor:
// todo gráfico tem legenda e os valores aparecem escritos.
const TOM_FORTE = "#525252";
const TOM_FRACO = "#a3a3a3";
const EIXO = "#737373";
const GRADE = "#e5e5e5";

const MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
const rotuloMes = (m: string) => {
  const [ano, mes] = m.split("-");
  return `${MESES[Number(mes) - 1]}/${ano.slice(2)}`;
};

const caixa = {
  background: "#fff",
  border: `1px solid ${GRADE}`,
  borderRadius: 6,
  fontSize: 12,
  color: "#0a0a0a",
};

export function SimulacoesPorMes({ dados }: { dados: { mes: string; simulacoes: number; leads: number }[] }) {
  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={dados.map((d) => ({ ...d, rotulo: rotuloMes(d.mes) }))} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}>
        <CartesianGrid vertical={false} stroke={GRADE} />
        <XAxis dataKey="rotulo" tickLine={false} axisLine={false} tick={{ fill: EIXO, fontSize: 12 }} />
        <YAxis allowDecimals={false} tickLine={false} axisLine={false} tick={{ fill: EIXO, fontSize: 12 }} width={32} />
        <Tooltip contentStyle={caixa} cursor={{ fill: "#00000008" }} />
        <Legend wrapperStyle={{ fontSize: 12, color: EIXO }} />
        {/* Barras com topo arredondado e folga entre elas, como manda o padrão. */}
        <Bar dataKey="simulacoes" name="Simulações" fill={TOM_FRACO} radius={[4, 4, 0, 0]} maxBarSize={38} />
        <Bar dataKey="leads" name="Confirmaram WhatsApp" fill={TOM_FORTE} radius={[4, 4, 0, 0]} maxBarSize={38} />
      </BarChart>
    </ResponsiveContainer>
  );
}

const TONS = [TOM_FORTE, TOM_FRACO, "#d4d4d4", "#737373"];

export function Rosca({ dados, total }: { dados: { rotulo: string; total: number }[]; total: number }) {
  if (!total) return <p className="py-10 text-center text-sm text-muted-foreground">Sem dados ainda.</p>;
  return (
    <div>
      <div className="relative">
        <ResponsiveContainer width="100%" height={180}>
          <PieChart>
            <Pie data={dados} dataKey="total" nameKey="rotulo" innerRadius={52} outerRadius={78}
              paddingAngle={2} stroke="#fff" strokeWidth={2}>
              {dados.map((_, i) => <Cell key={i} fill={TONS[i % TONS.length]} />)}
            </Pie>
            <Tooltip contentStyle={caixa} formatter={(v: any, n: any) => [`${v} simulação(ões)`, n]} />
          </PieChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-xs text-muted-foreground">Total</span>
          <span className="text-xl font-bold tabular-nums">{total}</span>
        </div>
      </div>

      {/* Legenda escrita: os tons são cinza, então a identidade nunca pode
          depender da cor. Cada fatia aparece com nome, contagem e percentual. */}
      <ul className="mt-3 space-y-1.5">
        {dados.map((d, i) => (
          <li key={d.rotulo} className="flex items-center gap-2 text-sm">
            <span className="h-2.5 w-2.5 flex-shrink-0 rounded-full" style={{ background: TONS[i % TONS.length] }} />
            <span className="flex-1 truncate capitalize">{d.rotulo}</span>
            <span className="tabular-nums text-muted-foreground">
              {d.total} · {Math.round((d.total / total) * 100)}%
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function PracasBarras({ dados }: {
  dados: { uf: string | null; praca_label: string; simulacoes: number; volume_proposta: number }[];
}) {
  const top = dados.slice(0, 5);
  const maximo = Math.max(...top.map((d) => d.simulacoes), 1);
  return (
    <ul className="space-y-3">
      {top.map((d, i) => (
        <li key={i} className="space-y-1">
          <div className="flex items-baseline justify-between gap-3 text-sm">
            <span className="truncate">
              <strong>{d.uf ?? "União"}</strong>
              <span className="text-muted-foreground"> · {d.praca_label}</span>
            </span>
            <span className="shrink-0 tabular-nums text-muted-foreground">
              {d.simulacoes} · {formatBRL(d.volume_proposta)}
            </span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-secondary">
            <div className="h-full rounded-full" style={{ width: `${(d.simulacoes / maximo) * 100}%`, background: TOM_FORTE }} />
          </div>
        </li>
      ))}
    </ul>
  );
}
