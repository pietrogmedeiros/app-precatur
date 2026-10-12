"use client";

// Leitura dos documentos (pré-análise, assistente de corte e modo autônomo).
//
// O que esta tela NUNCA faz: calcular com o que o modelo leu sem o advogado ver.
// A extração SEMEIA o formulário e mostra de que página cada número saiu — a
// conferência é humana. O OCR erra dígito (um centavo medido no caso 1063), e
// quem denuncia isso é a prova aritmética abaixo, não o modelo.

import { useState } from "react";
import { FileSearch, FileUp, Scissors, Loader2, Check, AlertTriangle } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Aviso, Opcoes, inputClass } from "./campos";
import {
  analisarPdf, extrairCortes, extrairPecas, preencherPorProcesso,
  type CorteSugerido, type EstadoDocumentos, type FormularioCalculo, type RespostaExtracao,
} from "@/lib/calculadora";

type Modo = "pecas" | "corte" | "autonomo";

/** Query params da extração → campos do formulário (mesmo vocabulário da tela antiga). */
export function semearFormulario(
  q: Record<string, string>
): { patch: Partial<FormularioCalculo>; crm: { numero_precatorio?: string; numero_oficio?: string } } {
  const patch: Partial<FormularioCalculo> = {};
  const direto: Record<string, keyof FormularioCalculo> = {
    vt: "vt", vp: "vp", vj: "vj", vs: "vs",
    hc: "hc", hs: "hs", natureza: "natureza", modalidade: "modalidade",
    data_calculo: "data_calculo", data_apres: "data_apres",
    ente_outro: "ente_outro", ref: "ref",
  };
  for (const [param, campo] of Object.entries(direto)) {
    if (q[param] !== undefined && q[param] !== "") (patch as any)[campo] = q[param];
  }
  if (q.ente) patch.ente = q.ente.startsWith("Outro") ? "outro" : q.ente;
  // A presença do valor escolhe o modo — é o que a tela antiga fazia pela URL.
  if (q.valor_pss) { patch.pss = q.valor_pss; patch.pss_modo = "valor"; }
  if (q.valor_ir) { patch.ir = q.valor_ir; patch.ir_modo = "valor"; }
  return {
    patch,
    crm: { numero_precatorio: q.numero_precatorio, numero_oficio: q.numero_oficio },
  };
}

export function Documentos({
  estado, aoSemear,
}: {
  estado: EstadoDocumentos;
  aoSemear: (patch: Partial<FormularioCalculo>, crm: { numero_precatorio?: string; numero_oficio?: string }) => void;
}) {
  const [modo, setModo] = useState<Modo>("pecas");
  const [ocupado, setOcupado] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [resultado, setResultado] = useState<RespostaExtracao | null>(null);

  // modo "peças já recortadas"
  const [conta, setConta] = useState<File | null>(null);
  const [oficio, setOficio] = useState<File | null>(null);
  const [sentencas, setSentencas] = useState<File[]>([]);

  // modo "assistente de corte"
  const [sessao, setSessao] = useState<string | null>(null);
  const [cortes, setCortes] = useState<CorteSugerido[]>([]);
  const [paginas, setPaginas] = useState<{ n: number; escaneadas: number } | null>(null);

  // modo autônomo
  const [processo, setProcesso] = useState<File | null>(null);

  async function tentar(rotulo: string, acao: () => Promise<RespostaExtracao | void>) {
    setOcupado(rotulo);
    setErro(null);
    try {
      const r = await acao();
      if (r) setResultado(r);
    } catch (e: any) {
      setErro(e?.message ?? "Falhou.");
    } finally {
      setOcupado(null);
    }
  }

  function aplicar() {
    if (!resultado?.query) return;
    const { patch, crm } = semearFormulario(resultado.query);
    aoSemear(patch, crm);
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-sm">
          <FileSearch className="h-4 w-4" /> Documentos do processo
        </CardTitle>
        <CardDescription className="text-xs">
          Preenche o formulário a partir dos PDFs. Os valores vêm com a página de onde saíram —
          confira antes de calcular.
          {!estado.ocr && " OCR indisponível neste ambiente: peça escaneada pode não ser lida."}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <Opcoes<Modo>
          label="Como os documentos chegaram"
          valor={modo}
          onChange={(v) => { setModo(v); setResultado(null); setErro(null); }}
          opcoes={[
            { valor: "pecas", rotulo: "Peças separadas" },
            { valor: "corte", rotulo: "Processo — eu marco os cortes" },
            { valor: "autonomo", rotulo: "Processo — acha sozinho" },
          ]}
        />

        {modo === "pecas" && (
          <div className="space-y-3">
            <Arquivo label="Conta homologada (obrigatória)" arquivo={conta} aoEscolher={setConta} />
            <Arquivo label="Ofício requisitório (opcional)" arquivo={oficio} aoEscolher={setOficio} />
            <Arquivo label="Sentenças / acórdãos (opcional)" multiplos
              arquivos={sentencas} aoEscolherVarios={setSentencas} />
            <Button type="button" disabled={!conta || !!ocupado}
              onClick={() => tentar("pecas", () => extrairPecas(conta!, oficio, sentencas))}>
              {ocupado === "pecas" ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileUp className="h-4 w-4" />}
              Extrair das peças
            </Button>
          </div>
        )}

        {modo === "corte" && (
          <div className="space-y-3">
            <Arquivo label="PDF do processo completo" arquivo={processo} aoEscolher={setProcesso} />
            <Button type="button" disabled={!processo || !!ocupado}
              onClick={() => tentar("analisar", async () => {
                const r = await analisarPdf(processo!);
                setSessao(r.sessao);
                setCortes(r.cortes_sugeridos ?? []);
                setPaginas({ n: r.n_paginas, escaneadas: r.escaneadas });
                setResultado(null);
              })}>
              {ocupado === "analisar" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Scissors className="h-4 w-4" />}
              Analisar e sugerir cortes
            </Button>

            {paginas && (
              <p className="text-xs text-muted-foreground">
                {paginas.n} páginas ({paginas.escaneadas} escaneadas). Confirme ou ajuste as faixas abaixo —
                a extração só roda sobre o que você marcar.
              </p>
            )}

            {cortes.length > 0 && (
              <div className="space-y-2">
                {cortes.map((c, i) => (
                  <div key={i} className="flex flex-wrap items-end gap-2 rounded-md border border-border/70 p-2">
                    <select className={`${inputClass} w-48`} value={c.tipo}
                      onChange={(e) => setCortes(cortes.map((x, j) => j === i ? { ...x, tipo: e.target.value } : x))}>
                      {["Conta homologada", "Ofício requisitório", "Outro / não usar"].map((t) => (
                        <option key={t} value={t}>{t}</option>
                      ))}
                    </select>
                    <label className="text-xs text-muted-foreground">
                      de
                      <input type="number" min={1} className={`${inputClass} ml-1 w-20`} value={c.pagina_inicio}
                        onChange={(e) => setCortes(cortes.map((x, j) => j === i ? { ...x, pagina_inicio: Number(e.target.value) } : x))} />
                    </label>
                    <label className="text-xs text-muted-foreground">
                      até
                      <input type="number" min={1} className={`${inputClass} ml-1 w-20`} value={c.pagina_fim}
                        onChange={(e) => setCortes(cortes.map((x, j) => j === i ? { ...x, pagina_fim: Number(e.target.value) } : x))} />
                    </label>
                    <button type="button" className="text-xs text-muted-foreground underline"
                      onClick={() => setCortes(cortes.filter((_, j) => j !== i))}>remover</button>
                  </div>
                ))}
                <div className="flex gap-2">
                  <Button type="button" variant="outline" size="sm"
                    onClick={() => setCortes([...cortes, { tipo: "Conta homologada", pagina_inicio: 1, pagina_fim: 1 }])}>
                    + faixa
                  </Button>
                  <Button type="button" disabled={!sessao || !!ocupado}
                    onClick={() => tentar("extrair", () => extrairCortes(sessao!, cortes.filter((c) => c.tipo !== "Outro / não usar")))}>
                    {ocupado === "extrair" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                    Extrair dos cortes
                  </Button>
                </div>
              </div>
            )}
          </div>
        )}

        {modo === "autonomo" && (
          <div className="space-y-3">
            <Arquivo label="PDF do processo completo" arquivo={processo} aoEscolher={setProcesso} />
            <Aviso tom="atencao">
              Neste modo o modelo escolhe sozinho qual é a conta homologada. Medido no corpus: ela fica em
              primeiro lugar em 54% das vezes — por isso confira a página de cada valor antes de calcular.
            </Aviso>
            <Button type="button" disabled={!processo || !!ocupado}
              onClick={() => tentar("autonomo", () => preencherPorProcesso(processo!))}>
              {ocupado === "autonomo" ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileUp className="h-4 w-4" />}
              Ler o processo
            </Button>
          </div>
        )}

        {erro && <Aviso tom="erro">{erro}</Aviso>}
        {resultado && <Extracao resultado={resultado} aoAplicar={aplicar} />}
      </CardContent>
    </Card>
  );
}

function Extracao({ resultado, aoAplicar }: { resultado: RespostaExtracao; aoAplicar: () => void }) {
  if (!resultado.ok) {
    return <Aviso tom="erro">Não consegui extrair: {resultado.erro}</Aviso>;
  }
  const campos = Object.entries(resultado.campos ?? {});
  const prova = resultado.prova;
  return (
    <div className="space-y-3">
      {prova?.ok === true && (
        <Aviso tom="info">✅ Prova aritmética bateu: principal + juros = total.</Aviso>
      )}
      {prova?.ok === false && (
        <Aviso tom="atencao">
          <AlertTriangle className="mr-1 inline h-3 w-3" />
          A prova aritmética NÃO fechou (diferença de {prova.dif_pct}%). Confira os valores antes de usar.
        </Aviso>
      )}
      {resultado.multi_conta && (
        <Aviso tom="atencao">Mais de uma conta marcada — a calculadora é um crédito por vez; usei a primeira.</Aviso>
      )}
      <div className="overflow-hidden rounded-md border border-border/70">
        <table className="w-full text-xs">
          <tbody>
            {campos.map(([nome, c]) => (
              <tr key={nome} className="border-b border-border/50 last:border-0">
                <td className="px-3 py-1.5 text-muted-foreground">{nome}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{c?.valor ?? "—"}</td>
                <td className="px-3 py-1.5 text-right text-[11px] text-muted-foreground/70">
                  {c?.citacao?.pagina ? `pág. ${c.citacao.pagina}` : ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Button type="button" onClick={aoAplicar} disabled={!resultado.query}>
        <Check className="h-4 w-4" /> Levar para o formulário
      </Button>
    </div>
  );
}

function Arquivo({
  label, arquivo, arquivos, aoEscolher, aoEscolherVarios, multiplos,
}: {
  label: string;
  arquivo?: File | null;
  arquivos?: File[];
  aoEscolher?: (f: File | null) => void;
  aoEscolherVarios?: (f: File[]) => void;
  multiplos?: boolean;
}) {
  return (
    <label className="block space-y-1.5">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      <input
        type="file"
        accept="application/pdf"
        multiple={multiplos}
        className="block w-full text-xs file:mr-3 file:rounded-md file:border file:border-input file:bg-transparent file:px-3 file:py-1.5 file:text-xs file:font-medium"
        onChange={(e) => {
          const fs = Array.from(e.target.files ?? []);
          if (multiplos) aoEscolherVarios?.(fs);
          else aoEscolher?.(fs[0] ?? null);
        }}
      />
      {multiplos
        ? arquivos && arquivos.length > 0 && (
            <span className="text-[11px] text-muted-foreground">{arquivos.length} arquivo(s)</span>
          )
        : arquivo && <span className="text-[11px] text-muted-foreground">{arquivo.name}</span>}
    </label>
  );
}
