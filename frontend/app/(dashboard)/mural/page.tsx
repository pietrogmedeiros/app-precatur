"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ClipboardList, Info, Calculator } from "lucide-react";
import { api, type PricingEntity } from "@/lib/api";
import { getUser } from "@/lib/auth";
import { cutRules, paymentHorizon } from "@/lib/pricing";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

function fmtDateTime(iso: string): string {
  const d = new Date(iso);
  return `${d.toLocaleDateString("pt-BR")} às ${d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}`;
}

// Mural de consulta rápida: por região, até que ano de previsão de pagamento
// ainda compramos e as regras de corte cadastradas. Sem percentuais e sem
// calculadora — é uma tela de leitura, feita para o Jurídico.
export default function MuralPage() {
  const [entities, setEntities] = useState<PricingEntity[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isJuridico, setIsJuridico] = useState(false);

  useEffect(() => {
    setIsJuridico(getUser()?.role === "juridico");
    api.pricing
      .list()
      .then(setEntities)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const atualizadoEm = useMemo(() => {
    const datas = entities.map((e) => e.updated_at).filter(Boolean).sort();
    return datas.length ? datas[datas.length - 1] : null;
  }, [entities]);

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-4 sm:p-6 md:p-8">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
            <ClipboardList className="h-6 w-6" />
            Mural · até que ano pagamos
          </h1>
          <p className="text-sm text-muted-foreground">
            O ano de previsão de pagamento que estamos pagando em cada região, e as regras de corte de cada uma.
          </p>
        </div>
        {isJuridico ? null : (
          <Link href="/precificacao">
            <Button variant="outline" className="gap-2">
              <Calculator className="h-4 w-4" />
              Abrir Precificação
            </Button>
          </Link>
        )}
      </header>

      {error ? <p className="rounded-md bg-secondary px-3 py-2 text-sm text-red-600">{error}</p> : null}

      {loading ? (
        <p className="py-10 text-center text-sm text-muted-foreground">Carregando…</p>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {entities.map((e) => {
              const h = paymentHorizon(e);
              const regras = cutRules(e);
              return (
                <Card key={e.key} className="flex flex-col">
                  <CardHeader className="pb-3">
                    <CardTitle className="text-base">{e.label}</CardTitle>
                    <CardDescription>{e.description}</CardDescription>
                  </CardHeader>
                  <CardContent className="flex flex-1 flex-col gap-3">
                    <div className="rounded-lg bg-primary p-4 text-primary-foreground">
                      <div className="text-[11px] font-medium uppercase tracking-wider opacity-80">
                        {h.until ? "Pagamos até a safra de" : "Regra"}
                      </div>
                      <div className="text-2xl font-bold tabular-nums">{h.until ?? h.ruleLabel ?? "—"}</div>
                      {h.until && h.from && h.from !== h.until ? (
                        <div className="text-xs opacity-80">Safras de {h.from} a {h.until}</div>
                      ) : null}
                    </div>

                    <div className="flex-1 space-y-1.5">
                      <div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                        Regras de corte
                      </div>
                      {regras.length ? (
                        <ul className="space-y-1.5 text-sm">
                          {regras.map((r, i) => (
                            <li key={i} className="flex gap-2">
                              <span className="text-muted-foreground">•</span>
                              <span>{r}</span>
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="text-sm text-muted-foreground">Sem regra adicional além das safras acima.</p>
                      )}
                    </div>
                  </CardContent>
                </Card>
              );
            })}
          </div>

          <p className="flex items-start gap-2 rounded-md bg-secondary px-3 py-2 text-xs text-muted-foreground">
            <Info className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" />
            <span>
              A safra é o ano previsto de pagamento do precatório — o mural mostra até que ano cada região é
              paga hoje. Os dados vêm da mesma tabela usada na Precificação, atualizada por um
              administrador
              {atualizadoEm ? `; última alteração em ${fmtDateTime(atualizadoEm)}` : ""}.
            </span>
          </p>
        </>
      )}
    </div>
  );
}
