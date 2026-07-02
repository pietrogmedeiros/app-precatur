"use client";

import { useEffect, useState } from "react";
import { Users, CheckCircle2, Trophy, Filter, Target, Wallet } from "lucide-react";
import { api, type SummaryMetrics, type FunnelStage, type TimeseriesPoint } from "@/lib/api";
import { KpiCard } from "@/components/kpi-card";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { FunnelChart } from "@/components/charts/funnel-chart";
import { RateRadial } from "@/components/charts/rate-radial";
import { TimeseriesArea } from "@/components/charts/timeseries-area";
import { formatCurrency, formatNumber, formatPercent } from "@/lib/utils";

export default function SalesPage() {
  const [summary, setSummary] = useState<SummaryMetrics | null>(null);
  const [funnel, setFunnel] = useState<FunnelStage[]>([]);
  const [series, setSeries] = useState<TimeseriesPoint[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.summary(), api.funnel(), api.timeseries()])
      .then(([s, f, t]) => {
        setSummary(s);
        setFunnel(f);
        setSeries(t);
      })
      .catch((e) => setError(e.message));
  }, []);

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-4 sm:p-6 md:p-8">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Dados Sales</h1>
        <p className="text-sm text-muted-foreground">Visão agregada do pipeline de vendas.</p>
      </header>

      {error ? (
        <Card>
          <CardContent className="p-6 text-sm text-muted-foreground">
            Não foi possível carregar os dados: {error}. Verifique se a API está no ar em{" "}
            <code>NEXT_PUBLIC_API_URL</code>.
          </CardContent>
        </Card>
      ) : null}

      {/* KPI row — the six Dados Sales metrics */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <KpiCard
          title="Total de Leads"
          value={summary ? formatNumber(summary.total_leads) : "—"}
          hint="Leads no período"
          icon={Users}
        />
        <KpiCard
          title="Qualificados"
          value={summary ? formatNumber(summary.qualificados) : "—"}
          hint="Alcançaram qualificação"
          icon={CheckCircle2}
        />
        <KpiCard
          title="Convertidos"
          value={summary ? formatNumber(summary.convertidos) : "—"}
          hint="Fechados como ganho"
          icon={Trophy}
        />
        <KpiCard
          title="Taxa de Qualificação"
          value={summary ? formatPercent(summary.taxa_qualificacao) : "—"}
          hint="Qualificados / Leads"
          icon={Filter}
        />
        <KpiCard
          title="Taxa de Conversão"
          value={summary ? formatPercent(summary.taxa_conversao) : "—"}
          hint="Convertidos / Qualificados"
          icon={Target}
        />
        <KpiCard
          title="Valor de Pipeline"
          value={summary ? formatCurrency(summary.valor_pipeline) : "—"}
          hint="Em aberto (novo + qualificado)"
          icon={Wallet}
        />
      </div>

      {/* Funnel + rate gauges */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-1">
          <CardHeader>
            <CardTitle>Funil de Conversão</CardTitle>
            <CardDescription>Leads → Qualificados → Convertidos</CardDescription>
          </CardHeader>
          <CardContent>
            {funnel.length ? <FunnelChart data={funnel} /> : <ChartSkeleton />}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Taxa de Qualificação</CardTitle>
            <CardDescription>Proporção de leads qualificados</CardDescription>
          </CardHeader>
          <CardContent>
            {summary ? (
              <RateRadial value={summary.taxa_qualificacao} label="Qualificação" />
            ) : (
              <ChartSkeleton />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Taxa de Conversão</CardTitle>
            <CardDescription>Qualificados que fecharam</CardDescription>
          </CardHeader>
          <CardContent>
            {summary ? (
              <RateRadial value={summary.taxa_conversao} label="Conversão" />
            ) : (
              <ChartSkeleton />
            )}
          </CardContent>
        </Card>
      </div>

      {/* Timeseries */}
      <Card>
        <CardHeader>
          <CardTitle>Evolução mensal</CardTitle>
          <CardDescription>Leads e convertidos ao longo do tempo</CardDescription>
        </CardHeader>
        <CardContent>
          {series.length ? <TimeseriesArea data={series} /> : <ChartSkeleton />}
        </CardContent>
      </Card>
    </div>
  );
}

function ChartSkeleton() {
  return <div className="h-[200px] w-full animate-pulse rounded-md bg-muted" />;
}
