"use client";

import { useEffect, useMemo, useState } from "react";
import { ArrowUpDown, ArrowUp, ArrowDown } from "lucide-react";
import { api, type OwnerMetrics } from "@/lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { OwnerBar } from "@/components/charts/owner-bar";
import { cn, formatCurrency, formatNumber, formatPercent } from "@/lib/utils";

type SortKey = keyof OwnerMetrics;

const COLUMNS: { key: SortKey; label: string; kind: "text" | "number" | "percent" | "currency" }[] = [
  { key: "owner", label: "Owner", kind: "text" },
  { key: "total_leads", label: "Total Leads", kind: "number" },
  { key: "qualificados", label: "Qualificados", kind: "number" },
  { key: "convertidos", label: "Convertidos", kind: "number" },
  { key: "taxa_qualificacao", label: "Taxa Qualif.", kind: "percent" },
  { key: "taxa_conversao", label: "Taxa Conv.", kind: "percent" },
  { key: "valor_pipeline", label: "Valor Pipeline", kind: "currency" },
];

function renderCell(kind: string, value: number | string) {
  if (kind === "text") return value as string;
  if (kind === "percent") return formatPercent(value as number);
  if (kind === "currency") return formatCurrency(value as number);
  return formatNumber(value as number);
}

export default function IndividualPage() {
  const [rows, setRows] = useState<OwnerMetrics[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("convertidos");
  const [asc, setAsc] = useState(false);

  useEffect(() => {
    api
      .byOwner()
      .then(setRows)
      .catch((e) => setError(e.message));
  }, []);

  const sorted = useMemo(() => {
    const copy = [...rows];
    copy.sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      let cmp: number;
      if (typeof av === "string" && typeof bv === "string") cmp = av.localeCompare(bv);
      else cmp = (av as number) - (bv as number);
      return asc ? cmp : -cmp;
    });
    return copy;
  }, [rows, sortKey, asc]);

  function toggleSort(key: SortKey) {
    if (key === sortKey) setAsc((v) => !v);
    else {
      setSortKey(key);
      setAsc(key === "owner");
    }
  }

  const totals = useMemo(() => {
    const leads = rows.reduce((s, r) => s + r.total_leads, 0);
    const conv = rows.reduce((s, r) => s + r.convertidos, 0);
    const pipe = rows.reduce((s, r) => s + r.valor_pipeline, 0);
    return { leads, conv, pipe, owners: rows.length };
  }, [rows]);

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-4 sm:p-6 md:p-8">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Dados Individuais</h1>
        <p className="text-sm text-muted-foreground">Desempenho por owner (vendedor).</p>
      </header>

      {error ? (
        <Card>
          <CardContent className="p-6 text-sm text-muted-foreground">
            Não foi possível carregar os dados: {error}.
          </CardContent>
        </Card>
      ) : null}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <MiniStat label="Owners" value={formatNumber(totals.owners)} />
        <MiniStat label="Leads (total)" value={formatNumber(totals.leads)} />
        <MiniStat label="Convertidos (total)" value={formatNumber(totals.conv)} />
        <MiniStat label="Pipeline (total)" value={formatCurrency(totals.pipe)} />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Comparativo por owner</CardTitle>
          <CardDescription>Leads, qualificados e convertidos</CardDescription>
        </CardHeader>
        <CardContent>
          {rows.length ? (
            <OwnerBar data={rows} />
          ) : (
            <div className="h-[320px] w-full animate-pulse rounded-md bg-muted" />
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Detalhamento</CardTitle>
          <CardDescription>Clique num cabeçalho para ordenar</CardDescription>
        </CardHeader>
        <CardContent className="px-0">
          <Table>
            <TableHeader>
              <TableRow>
                {COLUMNS.map((col) => {
                  const active = sortKey === col.key;
                  const Icon = active ? (asc ? ArrowUp : ArrowDown) : ArrowUpDown;
                  return (
                    <TableHead key={col.key} className={col.kind !== "text" ? "text-right" : ""}>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => toggleSort(col.key)}
                        className={cn(
                          "-ml-2 h-8 gap-1 px-2 font-medium",
                          col.kind !== "text" && "ml-auto",
                          active ? "text-foreground" : "text-muted-foreground"
                        )}
                      >
                        {col.label}
                        <Icon className="h-3.5 w-3.5" />
                      </Button>
                    </TableHead>
                  );
                })}
              </TableRow>
            </TableHeader>
            <TableBody>
              {sorted.map((row) => (
                <TableRow key={row.owner}>
                  {COLUMNS.map((col) => (
                    <TableCell
                      key={col.key}
                      className={cn(
                        col.kind === "text" ? "font-medium" : "text-right tabular-nums",
                        col.key === "owner" && "whitespace-nowrap"
                      )}
                    >
                      {renderCell(col.kind, row[col.key])}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
              {!sorted.length ? (
                <TableRow>
                  <TableCell colSpan={COLUMNS.length} className="py-10 text-center text-muted-foreground">
                    Carregando…
                  </TableCell>
                </TableRow>
              ) : null}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <Card>
      <CardContent className="p-4">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className="mt-1 text-xl font-semibold tabular-nums">{value}</p>
      </CardContent>
    </Card>
  );
}
