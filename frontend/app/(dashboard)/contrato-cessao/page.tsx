"use client";

// Instrumento Preliminar de Cessão Onerosa de Direitos Creditórios — o contrato
// que o closer manda o cedente assinar na fase da proposta.
//
// Mesmo molde do Termo de Vista: importa do Bitrix o que o card tem, o resto é
// digitado, e o PDF sai pela impressão do navegador com o papel timbrado. Nada
// é gravado: o contrato leva CPF/CNPJ, endereço e valores.
//
// O que muda de um contrato para outro (era vermelho no .docx do comercial):
// cedente (pessoa jurídica ou física, e o gênero em todo o texto), cessionária,
// ofício/tribunal/processo/vara, valores e local. O foro é sempre Vitória/ES.

import { useMemo, useState } from "react";
import { Download, FileSignature, Printer, RotateCcw } from "lucide-react";
import { api } from "@/lib/api";
import { fechaMoeda, maskMoeda, maskProcesso } from "@/lib/masks";
import {
  CESSIONARIA_PRECATUR,
  DADOS_VAZIOS,
  dataPorExtenso,
  derivar,
  formasDoCedente,
  formatarMoeda,
  tribunalPorExtenso,
  type DadosContrato,
} from "@/lib/contrato-cessao";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Corpo } from "./corpo";

const inputClass =
  "flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm outline-none focus-visible:ring-1 focus-visible:ring-ring";

export default function ContratoCessaoPage() {
  const [d, setD] = useState<DadosContrato>(DADOS_VAZIOS);
  const [bitrixRef, setBitrixRef] = useState("");
  const [buscando, setBuscando] = useState(false);
  const [aviso, setAviso] = useState<{ tom: "ok" | "erro"; texto: string } | null>(null);

  const mudar =
    <K extends keyof DadosContrato>(k: K, f?: (v: string) => string) =>
    (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
      const v = f ? f(e.target.value) : e.target.value;
      setD((cur) => ({ ...cur, [k]: v }));
    };
  const fechar = (k: "valorLiquido" | "preco") => () =>
    setD((cur) => ({ ...cur, [k]: fechaMoeda(cur[k]) }));

  const c = useMemo(() => formasDoCedente(d.tipo, d.genero), [d.tipo, d.genero]);
  const x = useMemo(() => derivar(d), [d]);
  const dataExt = dataPorExtenso(d.data);
  const anoPadrao = d.data ? Number(d.data.slice(0, 4)) : new Date().getFullYear();

  async function importar() {
    const ref = bitrixRef.trim();
    if (!ref) {
      setAviso({ tom: "erro", texto: "Cole o link ou o ID do deal." });
      return;
    }
    setBuscando(true);
    setAviso(null);
    try {
      const b = await api.bitrixDeal(ref);
      const doc = b.clientDoc ?? "";
      const pj = doc.replace(/\D/g, "").length === 14;
      // Parte do vazio: o que este card não tem não pode ficar do anterior. A
      // cessionária e o local são escolhas do closer, não do card: ficam.
      setD({
        ...DADOS_VAZIOS,
        cessNome: d.cessNome,
        cessCnpj: d.cessCnpj,
        cessEndereco: d.cessEndereco,
        cessRepresentante: d.cessRepresentante,
        local: d.local,
        tipo: pj ? "pj" : "pf",
        cedenteNome: b.nomeCompleto ?? "",
        cedenteDoc: doc,
        oficio: b.numeroOficio ?? "",
        tribunal: tribunalPorExtenso(b.tribunal),
        processo: b.processo ?? "",
      });
      const faltam = [
        !b.nomeCompleto && "nome",
        !doc && "CPF/CNPJ",
        !b.numeroOficio && "nº do ofício",
        !b.tribunal && "tribunal",
        !b.processo && "processo",
      ].filter(Boolean);
      setAviso({
        tom: "ok",
        texto:
          `Deal #${b.dealId} importado.` +
          (faltam.length ? ` O card não tem ${faltam.join(", ")}.` : "") +
          " Vara, valores, gênero e estado civil são preenchidos à mão.",
      });
    } catch (e: any) {
      setAviso({ tom: "erro", texto: e.message });
    } finally {
      setBuscando(false);
    }
  }

  function limpar() {
    setD(DADOS_VAZIOS);
    setBitrixRef("");
    setAviso(null);
  }

  // O Chrome sugere o document.title como nome do arquivo no "Salvar como PDF".
  function gerarPdf() {
    const anterior = document.title;
    const nome = d.cedenteNome
      .trim()
      .replace(/[\/\\:*?"<>|]+/g, "")
      .replace(/\s+/g, "_");
    document.title = nome ? `Contrato_Preliminar_${nome}` : "Contrato_Preliminar";
    const restaurar = () => {
      document.title = anterior;
      window.removeEventListener("afterprint", restaurar);
    };
    window.addEventListener("afterprint", restaurar);
    window.print();
  }

  const pj = d.tipo === "pj";
  const emBranco = (
    [
      [d.cedenteNome, "nome do cedente"],
      [d.cedenteDoc, pj ? "CNPJ do cedente" : "CPF do cedente"],
      [d.cedenteEndereco, pj ? "sede do cedente" : "endereço do cedente"],
      ...(pj
        ? []
        : ([
            [d.nacionalidade, "nacionalidade"],
            [d.estadoCivil, "estado civil"],
          ] as const)),
      [d.cessNome, "nome da cessionária"],
      [d.cessCnpj, "CNPJ da cessionária"],
      [d.cessEndereco, "sede da cessionária"],
      [d.cessRepresentante, "representante da cessionária"],
      [d.oficio, "nº do ofício"],
      [d.tribunal, "tribunal"],
      [d.processo, "processo de origem"],
      [d.vara, "vara"],
      [x.liquido === null ? "" : "ok", "valor líquido (1.2)"],
      [x.preco === null ? "" : "ok", "preço (2.1)"],
      [x.percentual ?? "", "percentual (1.3)"],
      [d.local, "local"],
    ] as ReadonlyArray<readonly [string, string]>
  )
    .filter(([v]) => !v.trim())
    .map(([, rotulo]) => rotulo);

  return (
    <div className="contrato-page mx-auto max-w-6xl space-y-8 p-4 sm:p-6 md:p-8">
      <header className="no-print flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
            <FileSignature className="h-6 w-6" /> Contrato Preliminar
          </h1>
          <p className="text-sm text-muted-foreground">
            Instrumento preliminar de cessão onerosa de direitos creditórios.
            Nada é salvo: o PDF sai na hora.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={limpar} className="gap-2">
            <RotateCcw className="h-4 w-4" /> Limpar
          </Button>
          <Button onClick={gerarPdf} className="gap-2">
            <Printer className="h-4 w-4" /> Gerar PDF
          </Button>
        </div>
      </header>

      <div className="contrato-layout grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)] lg:items-start">
        <div className="no-print space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Download className="h-4 w-4" /> Importar do Bitrix
              </CardTitle>
              <CardDescription>
                Traz nome, CPF/CNPJ, nº do ofício, tribunal e processo do card.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex gap-2">
                <input
                  className={inputClass}
                  placeholder="Link ou ID do deal"
                  value={bitrixRef}
                  onChange={(e) => setBitrixRef(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") importar();
                  }}
                />
                <Button onClick={importar} disabled={buscando} className="shrink-0">
                  {buscando ? "Buscando…" : "Buscar"}
                </Button>
              </div>
              {aviso ? (
                <p
                  className={
                    aviso.tom === "erro"
                      ? "rounded-md bg-secondary px-3 py-2 text-sm text-red-600 dark:text-red-400"
                      : "rounded-md bg-secondary px-3 py-2 text-sm"
                  }
                >
                  {aviso.texto}
                </p>
              ) : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Cedente</CardTitle>
              <CardDescription>
                A escolha de pessoa jurídica/física e o gênero trocam o texto
                todo de uma vez (a/o CEDENTE, à/ao, pela/pelo…).
              </CardDescription>
            </CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-2">
              <Rotulado rotulo="Tipo">
                <Alternativa
                  valor={d.tipo}
                  onChange={(v) => setD((cur) => ({ ...cur, tipo: v }))}
                  opcoes={[
                    ["pf", "Pessoa física"],
                    ["pj", "Pessoa jurídica"],
                  ]}
                />
              </Rotulado>
              <Rotulado rotulo="Gênero no texto">
                {pj ? (
                  <p className="flex h-9 items-center text-sm text-muted-foreground">
                    Pessoa jurídica: feminino (a CEDENTE).
                  </p>
                ) : (
                  <Alternativa
                    valor={d.genero}
                    onChange={(v) => setD((cur) => ({ ...cur, genero: v }))}
                    opcoes={[
                      ["m", "Masculino (o)"],
                      ["f", "Feminino (a)"],
                    ]}
                  />
                )}
              </Rotulado>
              <Rotulado rotulo={pj ? "Razão social" : "Nome completo"} className="sm:col-span-2">
                <input className={inputClass} value={d.cedenteNome} onChange={mudar("cedenteNome")} />
              </Rotulado>
              {pj ? null : (
                <>
                  <Rotulado rotulo="Nacionalidade">
                    <input
                      className={inputClass}
                      value={d.nacionalidade}
                      onChange={mudar("nacionalidade")}
                      placeholder={d.genero === "f" ? "brasileira" : "brasileiro"}
                    />
                  </Rotulado>
                  <Rotulado rotulo="Estado civil">
                    <input
                      className={inputClass}
                      value={d.estadoCivil}
                      onChange={mudar("estadoCivil")}
                      placeholder={d.genero === "f" ? "casada" : "casado"}
                    />
                  </Rotulado>
                </>
              )}
              <Rotulado rotulo={pj ? "CNPJ" : "CPF"} className="sm:col-span-2">
                <input className={inputClass} value={d.cedenteDoc} onChange={mudar("cedenteDoc")} />
              </Rotulado>
              <Rotulado
                rotulo={pj ? "Sede (endereço completo)" : "Residência (endereço completo)"}
                className="sm:col-span-2"
              >
                <input
                  className={inputClass}
                  value={d.cedenteEndereco}
                  onChange={mudar("cedenteEndereco")}
                  placeholder="Rua, número, complemento, bairro, cidade/UF, CEP"
                />
              </Rotulado>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Crédito</CardTitle>
              <CardDescription>
                O valor por extenso e a multa de 5% (item 4.3) saem sozinhos.
              </CardDescription>
            </CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-2">
              <Rotulado rotulo="Natureza do crédito" className="sm:col-span-2">
                <Alternativa
                  valor={d.natureza}
                  onChange={(v) => setD((cur) => ({ ...cur, natureza: v }))}
                  opcoes={[
                    ["honorarios", "Honorários contratuais"],
                    ["principal", "Crédito principal"],
                  ]}
                />
              </Rotulado>
              <Rotulado rotulo="Nº do ofício requisitório">
                <input className={inputClass} value={d.oficio} onChange={mudar("oficio")} />
              </Rotulado>
              <Rotulado rotulo="Processo de origem">
                <input
                  className={inputClass}
                  value={d.processo}
                  onChange={mudar("processo", maskProcesso)}
                />
              </Rotulado>
              <Rotulado rotulo="Tribunal que expediu" className="sm:col-span-2">
                <input
                  className={inputClass}
                  value={d.tribunal}
                  onChange={mudar("tribunal")}
                  placeholder="Ex.: Tribunal de Justiça do Estado do Pará"
                />
              </Rotulado>
              <Rotulado rotulo="Vara / juízo" className="sm:col-span-2">
                <input
                  className={inputClass}
                  value={d.vara}
                  onChange={mudar("vara")}
                  placeholder="Ex.: 4ª Vara da Fazenda da Capital"
                />
              </Rotulado>
              <Rotulado rotulo="Valor líquido do cedente (item 1.2)">
                <input
                  className={inputClass}
                  inputMode="decimal"
                  value={d.valorLiquido}
                  onChange={mudar("valorLiquido", maskMoeda)}
                  onBlur={fechar("valorLiquido")}
                  placeholder="285.045,82"
                />
              </Rotulado>
              <Rotulado rotulo="Percentual cedido (item 1.3)">
                <input
                  className={inputClass}
                  value={d.percentual}
                  onChange={mudar("percentual")}
                  placeholder="100"
                />
              </Rotulado>
              <Rotulado rotulo="Preço a pagar (item 2.1)">
                <input
                  className={inputClass}
                  inputMode="decimal"
                  value={d.preco}
                  onChange={mudar("preco", maskMoeda)}
                  onBlur={fechar("preco")}
                  placeholder="135.000,00"
                />
              </Rotulado>
              <Rotulado rotulo="Multa de exclusividade (5% do item 1.2)">
                <p className="flex h-9 items-center text-sm text-muted-foreground">
                  {x.multa === null ? "calculada quando houver valor líquido" : `R$ ${formatarMoeda(x.multa)}`}
                </p>
              </Rotulado>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Cessionária</CardTitle>
              <CardDescription>
                Padrão: a Precatur. Se o comprador for outro, troque os campos.
              </CardDescription>
            </CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-2">
              <Rotulado rotulo="Razão social" className="sm:col-span-2">
                <input className={inputClass} value={d.cessNome} onChange={mudar("cessNome")} />
              </Rotulado>
              <Rotulado rotulo="CNPJ">
                <input className={inputClass} value={d.cessCnpj} onChange={mudar("cessCnpj")} />
              </Rotulado>
              <Rotulado rotulo="Sócio administrador">
                <input
                  className={inputClass}
                  value={d.cessRepresentante}
                  onChange={mudar("cessRepresentante")}
                />
              </Rotulado>
              <Rotulado rotulo="Sede (endereço completo)" className="sm:col-span-2">
                <input className={inputClass} value={d.cessEndereco} onChange={mudar("cessEndereco")} />
              </Rotulado>
              <div className="sm:col-span-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setD((cur) => ({ ...cur, ...CESSIONARIA_PRECATUR }))}
                >
                  Usar os dados da Precatur
                </Button>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Assinatura</CardTitle>
              <CardDescription>
                Sem data, o PDF sai com a data em branco para preencher à mão.
              </CardDescription>
            </CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-2">
              <Rotulado rotulo="Local">
                <input
                  className={inputClass}
                  value={d.local}
                  onChange={mudar("local")}
                  placeholder="Ex.: Vitória/ES"
                />
              </Rotulado>
              <Rotulado rotulo="Data (opcional)">
                <input type="date" className={inputClass} value={d.data} onChange={mudar("data")} />
              </Rotulado>
              {emBranco.length > 0 && (
                <p className="text-xs text-muted-foreground sm:col-span-2">
                  Em branco no PDF: {emBranco.join(", ")}.
                </p>
              )}
            </CardContent>
          </Card>
        </div>

        <div className="contrato-preview space-y-3 lg:sticky lg:top-6">
          <p className="no-print text-sm font-medium text-muted-foreground">
            Pré-visualização · a divisão em páginas sai no PDF
          </p>
          <section className="contrato-doc">
            <div className="contrato-folha">
              <Corpo d={d} c={c} x={x} dataExt={dataExt} anoPadrao={anoPadrao} />
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}

function Rotulado({
  rotulo,
  className,
  children,
}: {
  rotulo: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div className={`space-y-1.5 ${className ?? ""}`}>
      <label className="text-sm font-medium">{rotulo}</label>
      {children}
    </div>
  );
}

/** Escolha entre poucas opções, em botões (mais claro que um select para 2 itens). */
function Alternativa<T extends string>({
  valor,
  onChange,
  opcoes,
}: {
  valor: T;
  onChange: (v: T) => void;
  opcoes: ReadonlyArray<readonly [T, string]>;
}) {
  return (
    <div className="flex gap-2">
      {opcoes.map(([v, rotulo]) => (
        <Button
          key={v}
          type="button"
          size="sm"
          variant={valor === v ? "default" : "outline"}
          onClick={() => onChange(v)}
          aria-pressed={valor === v}
        >
          {rotulo}
        </Button>
      ))}
    </div>
  );
}
