"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Chart,
  LineController,
  LineElement,
  PointElement,
  LinearScale,
  CategoryScale,
  Filler,
  Legend,
  Tooltip,
} from "chart.js";
import { Camera, Link2, Link2Off } from "lucide-react";
import { simulate, formatBRL, formatDecimal, parseBRL } from "@/lib/pricing";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

Chart.register(LineController, LineElement, PointElement, LinearScale, CategoryScale, Filler, Legend, Tooltip);

// Cores no tema claro do app (tokens neutros do shadcn em globals.css). Verde e
// vermelho seguem marcando os dois cenários, em tons que leem bem sobre branco.
const GREEN = "#059669";
const RED = "#dc2626";
const INK = "#0a0a0a"; // --foreground
const MUTED = "#737373"; // --muted-foreground
const GRID = "#e5e5e5"; // --border
const BG = "#ffffff"; // --card

const brl0 = (v: number) => formatBRL(v, 0);
const pct1 = (v: number) => v.toFixed(1).replace(".", ",") + "%";

export interface SimulatorSuggestion {
  antecipar: number; // proposta calculada → o que o cliente recebe hoje
  esperar: number; // valor cheio → o que o governo pagaria
  years: number | null; // prazo derivado da safra (null = safra sem ano)
}

export function Simulator({ suggested }: { suggested: SimulatorSuggestion }) {
  const [years, setYears] = useState(suggested.years ?? 5);
  const [cdi, setCdi] = useState(10.4);
  const [ipca, setIpca] = useState(4.5);
  const [ir, setIr] = useState(15);
  const [init1, setInit1] = useState(suggested.antecipar);
  const [spread1, setSpread1] = useState(5);
  const [init2, setInit2] = useState(suggested.esperar);
  const [spread2, setSpread2] = useState(1);
  // Enquanto "linked", aportes e prazo acompanham a calculadora. Editar qualquer
  // um deles à mão solta o vínculo, para a calculadora não atropelar o ajuste.
  const [linked, setLinked] = useState(true);
  const [text1, setText1] = useState(formatDecimal(suggested.antecipar));
  const [text2, setText2] = useState(formatDecimal(suggested.esperar));

  useEffect(() => {
    if (!linked) return;
    setInit1(suggested.antecipar);
    setInit2(suggested.esperar);
    setText1(formatDecimal(suggested.antecipar));
    setText2(formatDecimal(suggested.esperar));
    if (suggested.years !== null) setYears(Math.min(30, suggested.years));
  }, [linked, suggested.antecipar, suggested.esperar, suggested.years]);

  const data = useMemo(
    () => simulate({ years, cdi, ipca, ir, init1, spread1, init2, spread2 }),
    [years, cdi, ipca, ir, init1, spread1, init2, spread2]
  );

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const chartRef = useRef<Chart | null>(null);

  useEffect(() => {
    const ctx = canvasRef.current?.getContext("2d");
    if (!ctx) return;
    const grad = (rgb: string) => {
      const g = ctx.createLinearGradient(0, 0, 0, 350);
      g.addColorStop(0, `rgba(${rgb}, 0.12)`);
      g.addColorStop(1, `rgba(${rgb}, 0)`);
      return g;
    };
    chartRef.current = new Chart(ctx, {
      type: "line",
      data: {
        labels: [],
        datasets: [
          { label: "ANTECIPAR AGORA", data: [], borderColor: GREEN, backgroundColor: grad("5, 150, 105"), fill: true, tension: 0.35, borderWidth: 3, pointRadius: 3, pointHoverRadius: 6 },
          { label: "ESPERAR PELO GOVERNO", data: [], borderColor: RED, backgroundColor: grad("220, 38, 38"), fill: true, tension: 0.35, borderWidth: 3, pointRadius: 3, pointHoverRadius: 6 },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: "top", labels: { font: { size: 12, weight: 600 }, color: INK, usePointStyle: true, padding: 20 } },
          tooltip: {
            backgroundColor: BG,
            titleColor: INK,
            bodyColor: INK,
            borderColor: GRID,
            borderWidth: 1,
            callbacks: { label: (c) => ` ${c.dataset.label}: ${brl0(Number(c.raw))}` },
          },
        },
        scales: {
          x: { grid: { color: GRID }, ticks: { color: MUTED } },
          y: {
            grid: { color: GRID },
            ticks: {
              color: MUTED,
              callback: (v) => {
                const n = Number(v);
                if (n >= 1_000_000) return "R$ " + (n / 1_000_000).toFixed(1) + "M";
                if (n >= 1000) return "R$ " + (n / 1000).toFixed(0) + "k";
                return "R$ " + n;
              },
            },
          },
        },
      },
    });
    return () => {
      chartRef.current?.destroy();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    chart.data.labels = data.labels;
    chart.data.datasets[0].data = data.gross1;
    chart.data.datasets[1].data = data.gross2;
    chart.update();
  }, [data]);

  // Mesma exportação do gerador (agora em fundo claro, como a tela): esconde a série que não vai, desenha a faixa
  // com o líquido final por cima do gráfico e baixa o PNG. A faixa agora escala
  // com a densidade da tela — no original, em tela retina, o texto saía miúdo.
  function exportGraph(mode: "antecipar" | "esperar" | "ambos") {
    const chart = chartRef.current;
    const src = canvasRef.current;
    if (!chart || !src) return;
    const m0 = chart.getDatasetMeta(0);
    const m1 = chart.getDatasetMeta(1);
    const prev = [m0.hidden, m1.hidden];
    m0.hidden = mode === "esperar";
    m1.hidden = mode === "antecipar";
    chart.update("none");

    const k = src.width / (src.clientWidth || src.width);
    const banner = Math.round(80 * k);
    const out = document.createElement("canvas");
    out.width = src.width;
    out.height = src.height + banner;
    const c = out.getContext("2d")!;
    c.fillStyle = BG;
    c.fillRect(0, 0, out.width, out.height);
    c.font = `bold ${Math.round(15 * k)}px Inter, sans-serif`;

    const x = 20 * k;
    if (mode === "antecipar") {
      c.fillStyle = GREEN;
      c.fillText(`ANTECIPAR AGORA (Líquido Final): ${brl0(data.summary1.net)}`, x, 45 * k);
    } else if (mode === "esperar") {
      c.fillStyle = RED;
      c.fillText(`ESPERAR PELO GOVERNO (Líquido Final): ${brl0(data.summary2.net)}`, x, 45 * k);
    } else {
      c.fillStyle = GREEN;
      c.fillText(`ANTECIPAR AGORA (Líquido): ${brl0(data.summary1.net)}`, x, 35 * k);
      c.fillStyle = RED;
      c.fillText(`ESPERAR GOVERNO (Líquido): ${brl0(data.summary2.net)}`, x, 63 * k);
    }
    c.strokeStyle = GRID;
    c.lineWidth = k;
    c.beginPath();
    c.moveTo(x, banner - 5 * k);
    c.lineTo(out.width - x, banner - 5 * k);
    c.stroke();
    c.drawImage(src, 0, banner);

    const a = document.createElement("a");
    a.download = `grafico_${mode}_${new Date().toISOString().slice(0, 10)}.png`;
    a.href = out.toDataURL("image/png");
    a.click();

    m0.hidden = prev[0];
    m1.hidden = prev[1];
    chart.update("none");
  }

  const unlink = () => setLinked(false);

  return (
    <Card>
      <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between sm:space-y-0">
        <div className="space-y-1.5">
          <CardTitle>Antecipar agora × Esperar o governo</CardTitle>
          <CardDescription>
            Projeção para mostrar ao cliente quanto a antecipação rende frente à espera pelo pagamento.
          </CardDescription>
        </div>
        {linked ? (
          <span className="inline-flex shrink-0 items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs text-muted-foreground">
            <Link2 className="h-3.5 w-3.5" />
            Sincronizado com a calculadora
          </span>
        ) : (
          <Button variant="outline" size="sm" className="shrink-0 gap-1.5" onClick={() => setLinked(true)}>
            <Link2Off className="h-3.5 w-3.5" />
            Voltar a sincronizar com a calculadora
          </Button>
        )}
      </CardHeader>

      <CardContent className="space-y-5">
        <div className="grid gap-5 rounded-lg border bg-secondary/40 p-4 sm:grid-cols-2 lg:grid-cols-4">
          <Slider label="Prazo" value={years} display={`${years} ${years === 1 ? "ano" : "anos"}`} min={1} max={30} step={1}
            onChange={(v) => { setYears(v); unlink(); }} />
          <Slider label="Taxa CDI (% a.a.)" value={cdi} display={`${cdi}%`} min={3} max={20} step={0.1} onChange={setCdi} />
          <Slider label="IPCA estimado (% a.a.)" value={ipca} display={`${ipca}%`} min={1} max={15} step={0.1} onChange={setIpca} />
          <Slider label="Alíquota IR (%)" value={ir} display={`${ir.toFixed(1)}%`} min={0} max={22.5} step={2.5} onChange={setIr} />
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-4 rounded-lg border border-t-4 p-4" style={{ borderTopColor: GREEN }}>
            <h4 className="text-sm font-semibold tracking-wide" style={{ color: GREEN }}>ANTECIPAR AGORA</h4>
            <MoneyField label="Valor recebido hoje (proposta)" text={text1}
              onText={(t) => { setText1(t); unlink(); }}
              onCommit={() => { const v = parseBRL(text1); setInit1(v); setText1(formatDecimal(v)); }} />
            <Slider label="Prêmio sobre CDI (% a.a.)" value={spread1} display={`${spread1 >= 0 ? "+" : ""}${spread1}%`}
              min={-5} max={15} step={0.5} onChange={setSpread1} accent={GREEN} />
          </div>
          <div className="space-y-4 rounded-lg border border-t-4 p-4" style={{ borderTopColor: RED }}>
            <h4 className="text-sm font-semibold tracking-wide" style={{ color: RED }}>ESPERAR PELO GOVERNO</h4>
            <MoneyField label="Valor cheio do crédito" text={text2}
              onText={(t) => { setText2(t); unlink(); }}
              onCommit={() => { const v = parseBRL(text2); setInit2(v); setText2(formatDecimal(v)); }} />
            <Slider label="Prêmio sobre IPCA (% a.a.)" value={spread2} display={`${spread2 >= 0 ? "+" : ""}${spread2}%`}
              min={-2} max={10} step={0.5} onChange={setSpread2} accent={RED} />
          </div>
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <Summary title="Antecipar agora (líquido)" tone="green" rateLabel="CDI + prêmio" rate={data.rate1} s={data.summary1} />
          <Summary title="Esperar pelo governo (líquido)" tone="red" rateLabel="IPCA + prêmio" rate={data.rate2} s={data.summary2} />
        </div>

        <div className="flex flex-wrap justify-end gap-2">
          <ExportButton onClick={() => exportGraph("antecipar")}>Baixar &quot;Antecipar agora&quot;</ExportButton>
          <ExportButton onClick={() => exportGraph("esperar")}>Baixar &quot;Esperar governo&quot;</ExportButton>
          <ExportButton onClick={() => exportGraph("ambos")}>Baixar comparativo</ExportButton>
        </div>

        <div className="relative h-[320px] rounded-lg border p-4 sm:h-[420px]">
          <canvas ref={canvasRef} />
        </div>

        <p className="text-center text-xs text-muted-foreground">
          *Projeções simuladas com capitalização anual e IR sobre o ganho, ao final do período.
        </p>
      </CardContent>
    </Card>
  );
}

function Slider({ label, value, display, min, max, step, onChange, accent }: {
  label: string; value: number; display: string; min: number; max: number; step: number;
  onChange: (v: number) => void; accent?: string;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2 text-sm font-medium">
        <span>{label}</span>
        <span className="rounded-md bg-secondary px-2 py-0.5 text-xs font-semibold tabular-nums">{display}</span>
      </div>
      <input type="range" min={min} max={max} step={step} value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full cursor-pointer" style={{ accentColor: accent ?? INK }} />
    </div>
  );
}

function MoneyField({ label, text, onText, onCommit }: {
  label: string; text: string; onText: (t: string) => void; onCommit: () => void;
}) {
  return (
    <label className="block space-y-1.5 text-sm font-medium">
      <span>{label}</span>
      <div className="flex h-9 items-center rounded-md border border-input px-3 shadow-sm focus-within:ring-1 focus-within:ring-ring">
        <span className="text-muted-foreground">R$</span>
        <input value={text} inputMode="decimal"
          onChange={(e) => onText(e.target.value)} onBlur={onCommit}
          onKeyDown={(e) => e.key === "Enter" && onCommit()}
          className="h-full w-full bg-transparent px-2 text-sm outline-none" />
      </div>
    </label>
  );
}

function Summary({ title, tone, rateLabel, rate, s }: {
  title: string; tone: "green" | "red"; rateLabel: string; rate: number;
  s: { gross: number; tax: number; net: number };
}) {
  const box = tone === "green" ? "border-emerald-200 bg-emerald-50" : "border-red-200 bg-red-50";
  const color = tone === "green" ? GREEN : RED;
  return (
    <div className={`rounded-lg border p-4 ${box}`}>
      <div className="mb-1 text-xs font-semibold uppercase tracking-wider" style={{ color }}>{title}</div>
      <div className="mb-3 text-2xl font-bold tabular-nums">{brl0(s.net)}</div>
      <div className="space-y-1 border-t border-black/5 pt-2 text-xs text-muted-foreground">
        <Line k={`Taxa bruta (${rateLabel})`} v={pct1(rate)} />
        <Line k="Montante bruto" v={brl0(s.gross)} />
        <Line k="Imposto estimado" v={brl0(s.tax)} />
      </div>
    </div>
  );
}

function Line({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between gap-3">
      <span>{k}</span>
      <strong className="tabular-nums text-foreground">{v}</strong>
    </div>
  );
}

function ExportButton({ onClick, children }: { onClick: () => void; children: React.ReactNode }) {
  return (
    <Button variant="outline" size="sm" className="gap-2" onClick={onClick}>
      <Camera className="h-3.5 w-3.5" />
      {children}
    </Button>
  );
}
