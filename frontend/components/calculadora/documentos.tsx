"use client";

// Leitura dos documentos (pré-análise, assistente de corte e modo autônomo).
//
// O que esta tela NUNCA faz: calcular com o que o modelo leu sem o advogado ver.
// A extração SEMEIA o formulário e mostra de que página cada número saiu — a
// conferência é humana. O OCR erra dígito (um centavo medido no caso 1063), e
// quem denuncia isso é a prova aritmética abaixo, não o modelo.

import { useState } from "react";
import { FileSearch, FileUp, Scissors, Loader2, Check, AlertTriangle, Eye } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Aviso, Opcoes, inputClass } from "./campos";
import {
  analisarPdf, extrairCortes, extrairPecas, paginasCitadas, preencherPorProcesso,
  type CorteSugerido, type EstadoDocumentos, type FormularioCalculo,
  type PaginaCitada, type RespostaExtracao,
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

  // Os valores recusados (que a IA propôs e não existem na conta) só entram se
  // o advogado tiver marcado "usar mesmo assim" — a recusa é a trava contra a
  // agregação, e desfazê-la é decisão dele, não do código.
  function aplicar(usados: Set<string>) {
    if (!resultado?.query) return;
    const query = { ...resultado.query };
    for (const r of resultado.rejeitados ?? []) {
      if (usados.has(r.param)) query[r.param] = String(r.valor);
    }
    const { patch, crm } = semearFormulario(query);
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
        {!estado.llm && (
          <Aviso tom="atencao">
            A leitura dos documentos está ligada, mas <strong>falta a chave do modelo</strong>
            {" "}(<code>OPENROUTER_API_KEY</code>) neste ambiente. Os valores do formulário
            continuam sendo digitados à mão; o cálculo e o memorial não dependem disto.
          </Aviso>
        )}

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
            <Button type="button" disabled={!conta || !!ocupado || !estado.llm}
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
                  <Button type="button" disabled={!sessao || !!ocupado || !estado.llm}
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
            <Button type="button" disabled={!processo || !!ocupado || !estado.llm}
              onClick={() => tentar("autonomo", () => preencherPorProcesso(processo!))}>
              {ocupado === "autonomo" ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileUp className="h-4 w-4" />}
              Ler o processo
            </Button>
          </div>
        )}

        {erro && <Aviso tom="erro">{erro}</Aviso>}
        {resultado && <Extracao key={resultado.sessao_paginas ?? "x"} resultado={resultado} aoAplicar={aplicar} />}
      </CardContent>
    </Card>
  );
}

function Extracao({
  resultado, aoAplicar,
}: {
  resultado: RespostaExtracao;
  aoAplicar: (usados: Set<string>) => void;
}) {
  const [usados, setUsados] = useState<Set<string>>(new Set());
  const [paginas, setPaginas] = useState<PaginaCitada[] | null>(null);
  const [vendo, setVendo] = useState(false);
  const [erroPaginas, setErroPaginas] = useState<string | null>(null);

  if (!resultado.ok) {
    return <Aviso tom="erro">Não consegui extrair: {resultado.erro}</Aviso>;
  }
  const campos = Object.entries(resultado.campos ?? {});
  const prova = resultado.prova;
  const mapa = resultado.mapa_paginas ?? {};

  /** "Conta homologada, pág 3" — a página do espaço concatenado não localiza nada. */
  function onde(pagina?: number): string {
    if (!pagina) return "";
    const m = mapa[String(pagina)];
    return m ? `${m.peca}, pág. ${m.pagina}` : `pág. ${pagina}`;
  }

  async function verPaginas() {
    if (!resultado.sessao_paginas) return;
    setVendo(true);
    setErroPaginas(null);
    try {
      setPaginas((await paginasCitadas(resultado.sessao_paginas)).paginas);
    } catch (e: any) {
      setErroPaginas(e?.message ?? "Não consegui renderizar as páginas.");
    } finally {
      setVendo(false);
    }
  }

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
      <p className="text-xs text-muted-foreground">
        <strong>Valores extraídos</strong> — o trecho mostra de onde cada número saiu.
      </p>
      <div className="overflow-hidden rounded-md border border-border/70">
        <table className="w-full text-xs">
          <tbody>
            {campos.map(([nome, c]) => (
              <tr key={nome} className="border-b border-border/50 align-top last:border-0">
                <td className="px-3 py-1.5">
                  <span className="text-muted-foreground">{nome}</span>
                  {c?.citacao?.trecho && (
                    <span className="mt-0.5 block text-[11px] italic text-muted-foreground/70">
                      “{c.citacao.trecho}”
                    </span>
                  )}
                </td>
                <td className="whitespace-nowrap px-3 py-1.5 text-right tabular-nums">{c?.valor ?? "—"}</td>
                <td className="whitespace-nowrap px-3 py-1.5 text-right text-[11px] text-muted-foreground/70">
                  {onde(c?.citacao?.pagina)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {(resultado.conflitos ?? []).map((cf) => (
        <Aviso key={cf.campo} tom="atencao">
          <AlertTriangle className="mr-1 inline h-3 w-3" />
          <strong>{cf.campo}</strong>: a IA leu <code>{cf.llm ?? "nada"}</code> e a regra determinística
          leu <code>{cf.regex}</code>{cf.pagina ? ` (${onde(cf.pagina)})` : ""} — confira qual está certo.
        </Aviso>
      ))}

      {(resultado.rejeitados ?? []).map((r) => (
        <Aviso key={r.param} tom="erro">
          <strong>{r.campo}</strong>: a IA propôs <code>{r.valor}</code>, mas esse número{" "}
          <strong>não existe em nenhuma página da conta</strong> — o campo ficou <strong>vazio</strong>.
          Costuma ser soma de linhas: legítima quando são verbas ou períodos do mesmo credor, indevida
          quando entra honorário ou sucumbência.
          {r.citacao?.trecho && (
            <span className="mt-1 block text-[11px] italic">Trecho citado pela IA: “{r.citacao.trecho}”</span>
          )}
          <label className="mt-1.5 flex items-center gap-2 text-[11px]">
            <input type="checkbox" checked={usados.has(r.param)}
              onChange={(e) => setUsados((s) => {
                const novo = new Set(s);
                if (e.target.checked) novo.add(r.param); else novo.delete(r.param);
                return novo;
              })} />
            Usar <code>{r.valor}</code> mesmo assim
          </label>
        </Aviso>
      ))}

      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" onClick={() => aoAplicar(usados)} disabled={!resultado.query}>
          <Check className="h-4 w-4" /> Levar para o formulário
        </Button>
        {resultado.sessao_paginas && !paginas && (
          <Button type="button" variant="outline" onClick={verPaginas} disabled={vendo}>
            {vendo ? <Loader2 className="h-4 w-4 animate-spin" /> : <Eye className="h-4 w-4" />}
            Ver as páginas citadas
          </Button>
        )}
      </div>

      {erroPaginas && <Aviso tom="erro">{erroPaginas}</Aviso>}
      {paginas?.length === 0 && (
        <Aviso tom="info">Não há páginas citadas para mostrar nesta extração.</Aviso>
      )}
      {paginas && paginas.length > 0 && (
        <div className="space-y-3">
          {paginas.map((p) => (
            <figure key={`${p.peca}-${p.pagina}`} className="space-y-1">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={`data:image/png;base64,${p.png}`} alt={`${p.peca} — página ${p.pagina}`}
                className="w-full rounded-md border border-border/70" />
              <figcaption className="text-[11px] text-muted-foreground">
                {p.peca} — pág. {p.pagina} ·{" "}
                {p.n_marcas > 0
                  ? `${p.n_marcas} valor(es) destacado(s)`
                  : "nenhum destaque: o número não está escrito assim nesta página"}
              </figcaption>
            </figure>
          ))}
        </div>
      )}
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
